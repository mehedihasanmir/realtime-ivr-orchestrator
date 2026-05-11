from __future__ import annotations

import asyncio
import base64
import json
import logging
import audioop
from dataclasses import dataclass, field
from typing import Callable, Optional

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from app.core.config import Settings

logger = logging.getLogger(__name__)

_SILENCE_THRESHOLD_SECONDS = 1.0
_SILENCE_POLL_INTERVAL = 0.5
_MIN_AUDIO_SECONDS = 0.1

_AUDIO_BYTES_PER_SECOND = {
    "g711_ulaw": 8000,
    "g711_alaw": 8000,
    "pcm16": 32000,
}


def _estimate_base64_bytes(encoded: str) -> int:
    padding = encoded.count("=")
    return max(0, (len(encoded) * 3) // 4 - padding)


@dataclass
class _BridgeState:
    stream_sid: Optional[str] = None
    last_audio_time: Optional[float] = None
    response_in_progress: bool = False
    response_audio_started: bool = False
    speech_frame_count: int = 0
    last_rms_log_time: Optional[float] = None
    buffered_audio_bytes: int = 0
    twilio_closed: bool = False
    user_id: Optional[str] = None


class RealtimeBridge:
    """Bridges a Twilio WebSocket with the OpenAI Realtime API."""

    def __init__(
        self,
        settings: Settings,
        schedule_meeting: Callable[[str, Optional[str]], str],
    ) -> None:
        self.settings = settings
        self.schedule_meeting = schedule_meeting
        self._input_audio_format = settings.openai_input_audio_format.lower()
        self._barge_in_rms_threshold = settings.barge_in_rms_threshold
        self._barge_in_trigger_frames = settings.barge_in_trigger_frames
        bytes_per_second = _AUDIO_BYTES_PER_SECOND.get(
            self._input_audio_format,
            _AUDIO_BYTES_PER_SECOND["g711_ulaw"],
        )
        self._min_audio_bytes = int(bytes_per_second * _MIN_AUDIO_SECONDS)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self, twilio_ws: WebSocket, default_context: str = "No data provided.") -> None:
        try:
            async with websockets.connect(
                self.settings.openai_realtime_url,
                additional_headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key}",
                    "OpenAI-Beta": "realtime=v1",
                },
            ) as openai_ws:
                logger.info("Connected to OpenAI Realtime API")
                state = _BridgeState()
                silence_task = asyncio.create_task(
                    self._silence_watcher(openai_ws, state)
                )
                try:
                    await asyncio.gather(
                        self._receive_from_twilio(twilio_ws, openai_ws, state, default_context),
                        self._receive_from_openai(twilio_ws, openai_ws, state),
                        return_exceptions=True,
                    )
                finally:
                    silence_task.cancel()
                    await asyncio.gather(silence_task, return_exceptions=True)
        except Exception as exc:
            logger.exception("OpenAI WebSocket connection error: %s", exc)
            try:
                await twilio_ws.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Silence watcher
    # ------------------------------------------------------------------

    async def _silence_watcher(self, openai_ws, state: _BridgeState) -> None:
        """Commit the audio buffer after a period of silence and request a response."""
        while True:
            await asyncio.sleep(_SILENCE_POLL_INTERVAL)

            if state.twilio_closed:
                return

            now = asyncio.get_running_loop().time()  # 3.10+ safe replacement for get_event_loop()
            if (
                state.last_audio_time is not None
                and (now - state.last_audio_time) > _SILENCE_THRESHOLD_SECONDS
                and not state.response_in_progress  # avoid double-trigger
            ):
                state.last_audio_time = None  # reset before the await to avoid re-entry
                if state.buffered_audio_bytes < self._min_audio_bytes:
                    logger.info(
                        "Audio silence detected but buffer too small (%d bytes); skipping commit",
                        state.buffered_audio_bytes,
                    )
                    continue
                logger.info("Audio silence detected — committing buffer")
                try:
                    await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    await asyncio.sleep(0.2)
                    await openai_ws.send(json.dumps({"type": "response.create"}))
                    state.response_in_progress = True
                    state.buffered_audio_bytes = 0
                except Exception as exc:
                    logger.exception("Error committing audio buffer: %s", exc)

    # ------------------------------------------------------------------
    # Twilio → OpenAI
    # ------------------------------------------------------------------

    async def _receive_from_twilio(
        self,
        twilio_ws: WebSocket,
        openai_ws,
        state: _BridgeState,
        default_context: str,
    ) -> None:
        try:
            async for raw in twilio_ws.iter_text():
                data = json.loads(raw)
                event = data.get("event")

                if event == "media":
                    audio_payload = data.get("media", {}).get("payload")
                    if audio_payload:
                        if state.response_in_progress and state.response_audio_started:
                            if self._detect_barge_in(audio_payload, state):
                                await self._handle_barge_in(
                                    twilio_ws, openai_ws, state, confirmed_speech=False
                                )
                        state.last_audio_time = asyncio.get_running_loop().time()
                        state.buffered_audio_bytes += _estimate_base64_bytes(audio_payload)
                        logger.debug("Received audio from Twilio: %d chars", len(audio_payload))
                        await openai_ws.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": audio_payload,
                                }
                            )
                        )

                elif event == "start":
                    start = data.get("start", {})
                    state.stream_sid = start.get("streamSid")
                    state.buffered_audio_bytes = 0
                    state.twilio_closed = False
                    custom_params = (
                        start.get("customParameters")
                        or start.get("streamDetails", {}).get("customParameters", {})
                        or {}
                    )
                    state.user_id = custom_params.get("user_id")
                    website_data = custom_params.get("scraped_data") or default_context
                    logger.info("Stream started — SID: %s", state.stream_sid)
                    await self._send_session_update(openai_ws, website_data)

                elif event == "stop":
                    logger.info("Call ended by Twilio")
                    state.twilio_closed = True
                    break

        except WebSocketDisconnect:
            logger.info("Twilio WebSocket disconnected")
            state.twilio_closed = True
        except ConnectionClosed:
            logger.info("Twilio WebSocket closed")
            state.twilio_closed = True
        except Exception as exc:
            logger.exception("Error receiving from Twilio: %s", exc)
            state.twilio_closed = True

    async def _send_session_update(self, openai_ws, website_data: str) -> None:
        session_update = {
            "type": "session.update",
            "session": {
                "turn_detection": self.settings.openai_turn_detection,
                "input_audio_format": self.settings.openai_input_audio_format,
                "output_audio_format": self.settings.openai_output_audio_format,
                "voice": self.settings.openai_voice,
                "instructions": (
                    "You are a helpful assistant. "
                    f"Context: {website_data}. "
                    "If the user wants to book a meeting, call the 'schedule_meeting' tool. "
                    "Always respond with clear audio. Be conversational and friendly."
                ),
                "modalities": list(self.settings.openai_modalities),
                "temperature": self.settings.openai_temperature,
                "max_response_output_tokens": self.settings.openai_max_tokens,
                "tools": [
                    {
                        "type": "function",
                        "name": "schedule_meeting",
                        "description": "Schedule a meeting on the calendar",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "user_request": {
                                    "type": "string",
                                    "description": (
                                        "The user's spoken request "
                                        "(e.g., 'next Tuesday at 4pm')"
                                    ),
                                }
                            },
                            "required": ["user_request"],
                        },
                    }
                ],
            },
        }
        await openai_ws.send(json.dumps(session_update))
        logger.info("OpenAI session configured")

    # ------------------------------------------------------------------
    # OpenAI → Twilio
    # ------------------------------------------------------------------

    async def _receive_from_openai(
        self, twilio_ws: WebSocket, openai_ws, state: _BridgeState
    ) -> None:
        try:
            async for raw in openai_ws:
                try:
                    response = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from OpenAI: %s", raw)
                    continue

                response_type = response.get("type")

                if response_type == "error":
                    error_msg = response.get("error", {}).get("message", "Unknown error")
                    logger.error("OpenAI error: %s", error_msg)
                    state.response_in_progress = False

                elif response_type == "response.created":
                    state.response_in_progress = True
                    state.response_audio_started = False
                    state.speech_frame_count = 0
                    logger.info("Response generation started")

                elif response_type == "response.audio.delta":
                    await self._forward_audio_to_twilio(twilio_ws, state, response)

                elif response_type == "response.text.delta":
                    logger.debug("Text delta: %s", response.get("delta", ""))

                elif response_type == "input_audio_buffer.speech_started":
                    logger.debug("OpenAI VAD: speech_started")
                    await self._handle_barge_in(
                        twilio_ws, openai_ws, state, confirmed_speech=True
                    )

                elif response_type == "response.done":
                    state.response_in_progress = False
                    state.response_audio_started = False
                    state.speech_frame_count = 0
                    logger.info("Response complete")

                elif response_type == "response.function_call_arguments.done":
                    if response.get("name") == "schedule_meeting":
                        await self._handle_schedule_meeting(openai_ws, response, state)

        except ConnectionClosed:
            logger.warning("OpenAI WebSocket closed")
        except Exception as exc:
            logger.exception("Error receiving from OpenAI: %s", exc)

    async def _forward_audio_to_twilio(
        self, twilio_ws: WebSocket, state: _BridgeState, response: dict
    ) -> None:
        if not state.response_in_progress:
            logger.debug("Dropping audio delta while response is not active")
            return
        if not state.response_audio_started:
            state.response_audio_started = True
        audio_payload = response.get("delta")
        if not audio_payload:
            logger.warning("Audio delta received without payload")
            return
        if state.twilio_closed:
            logger.debug("Twilio connection closed; skipping audio send")
            return
        if not state.stream_sid:
            logger.warning("Missing stream SID — cannot forward audio")
            return
        try:
            await twilio_ws.send_json(
                {
                    "event": "media",
                    "streamSid": state.stream_sid,
                    "media": {"payload": audio_payload},
                }
            )
        except Exception as exc:
            logger.exception("Error forwarding audio to Twilio: %s", exc)
            state.twilio_closed = True

    async def _handle_schedule_meeting(
        self, openai_ws, response: dict, state: _BridgeState
    ) -> None:
        call_id = response.get("call_id")
        if not call_id:
            logger.warning("schedule_meeting call missing call_id: %s", response)
            return

        result_text = "Error: schedule_meeting failed."
        try:
            args = json.loads(response.get("arguments", "{}"))
            user_request = args.get("user_request")
            if not user_request:
                logger.warning("schedule_meeting called without user_request argument")
                result_text = "Error: schedule_meeting called without user_request."
            else:
                result_text = await asyncio.to_thread(
                    self.schedule_meeting, user_request, state.user_id
                )
        except Exception as exc:
            logger.exception("Error handling schedule_meeting: %s", exc)
            result_text = f"Error: schedule_meeting failed: {exc}"

        try:
            await openai_ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": result_text,
                        },
                    }
                )
            )
            await asyncio.sleep(0.2)
            await openai_ws.send(json.dumps({"type": "response.create"}))
        except Exception as exc:
            logger.exception("Error sending schedule_meeting output: %s", exc)

    async def _handle_barge_in(
        self,
        twilio_ws: WebSocket,
        openai_ws,
        state: _BridgeState,
        confirmed_speech: bool = False,
    ) -> None:
        if not state.response_in_progress:
            return
        if not confirmed_speech and not state.response_audio_started:
            return
        logger.info("Barge-in detected — cancelling response and clearing Twilio audio")
        try:
            await openai_ws.send(json.dumps({"type": "response.cancel"}))
        except Exception as exc:
            logger.exception("Error cancelling response: %s", exc)
        state.response_in_progress = False
        state.response_audio_started = False
        state.speech_frame_count = 0
        await self._clear_twilio_audio(twilio_ws, state)

    async def _clear_twilio_audio(self, twilio_ws: WebSocket, state: _BridgeState) -> None:
        if state.twilio_closed or not state.stream_sid:
            return
        try:
            await twilio_ws.send_json(
                {
                    "event": "clear",
                    "streamSid": state.stream_sid,
                }
            )
        except Exception as exc:
            logger.exception("Error clearing Twilio audio: %s", exc)
            state.twilio_closed = True

    def _detect_barge_in(self, audio_payload: str, state: _BridgeState) -> bool:
        rms = self._audio_rms(audio_payload)
        if rms is None:
            return False
        self._log_barge_in_rms(rms, state)
        if rms >= self._barge_in_rms_threshold:
            state.speech_frame_count += 1
        else:
            state.speech_frame_count = 0
        if state.speech_frame_count >= self._barge_in_trigger_frames:
            state.speech_frame_count = 0
            return True
        return False

    def _log_barge_in_rms(self, rms: int, state: _BridgeState) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return
        if state.last_rms_log_time is None or (now - state.last_rms_log_time) >= 1.0:
            state.last_rms_log_time = now
            logger.debug(
                "Barge-in RMS=%s threshold=%s frames=%s",
                rms,
                self._barge_in_rms_threshold,
                state.speech_frame_count,
            )

    def _audio_rms(self, audio_payload: str) -> Optional[int]:
        try:
            raw = base64.b64decode(audio_payload)
        except Exception:
            return None
        if not raw:
            return None
        try:
            if self._input_audio_format == "pcm16":
                return audioop.rms(raw, 2)
            if self._input_audio_format == "g711_ulaw":
                pcm = audioop.ulaw2lin(raw, 2)
                return audioop.rms(pcm, 2)
            if self._input_audio_format == "g711_alaw":
                pcm = audioop.alaw2lin(raw, 2)
                return audioop.rms(pcm, 2)
        except Exception:
            return None
        return None

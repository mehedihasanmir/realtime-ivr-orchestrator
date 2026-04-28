from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Callable, Optional

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class _BridgeState:
    stream_sid: Optional[str] = None
    last_audio_time: Optional[float] = None
    response_in_progress: bool = False


class RealtimeBridge:
    def __init__(self, settings: Settings, schedule_meeting: Callable[[str], str]) -> None:
        self.settings = settings
        self.schedule_meeting = schedule_meeting

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
                audio_task = asyncio.create_task(
                    self._commit_audio_buffer_after_silence(openai_ws, state)
                )
                try:
                    await asyncio.gather(
                        self._receive_from_twilio(twilio_ws, openai_ws, state, default_context),
                        self._receive_from_openai(twilio_ws, openai_ws, state),
                        return_exceptions=True,
                    )
                finally:
                    audio_task.cancel()
                    await asyncio.gather(audio_task, return_exceptions=True)
        except Exception as exc:
            logger.exception("OpenAI WebSocket connection error: %s", exc)
            try:
                await twilio_ws.close()
            except Exception:
                pass

    async def _commit_audio_buffer_after_silence(self, openai_ws, state: _BridgeState) -> None:
        while True:
            await asyncio.sleep(0.5)
            if state.last_audio_time and (asyncio.get_event_loop().time() - state.last_audio_time) > 1.0:
                logger.info("Audio silence detected, committing buffer")
                try:
                    await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    await asyncio.sleep(0.2)
                    if not state.response_in_progress:
                        await openai_ws.send(json.dumps({"type": "response.create"}))
                        state.response_in_progress = True
                    state.last_audio_time = None
                except Exception as exc:
                    logger.exception("Error committing audio buffer: %s", exc)

    async def _receive_from_twilio(
        self,
        twilio_ws: WebSocket,
        openai_ws,
        state: _BridgeState,
        default_context: str,
    ) -> None:
        try:
            async for message in twilio_ws.iter_text():
                data = json.loads(message)
                event = data.get("event")

                if event == "media":
                    state.last_audio_time = asyncio.get_event_loop().time()
                    audio_payload = data.get("media", {}).get("payload")
                    if audio_payload:
                        logger.debug("Received audio from Twilio: %s bytes", len(audio_payload))
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
                    custom_params = (
                        start.get("customParameters")
                        or start.get("streamDetails", {}).get("customParameters", {})
                        or {}
                    )
                    website_data = custom_params.get("scraped_data") or default_context
                    logger.info("Stream started. SID: %s", state.stream_sid)
                    await self._send_session_update(openai_ws, website_data)

                elif event == "stop":
                    logger.info("Call ended by Twilio")
                    break
        except WebSocketDisconnect:
            logger.info("Twilio WebSocket disconnected")
        except ConnectionClosed:
            logger.info("Twilio WebSocket closed")
        except Exception as exc:
            logger.exception("Error receiving from Twilio: %s", exc)

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
                                    "description": "The user's spoken request (e.g., 'next Tuesday at 4pm')",
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

    async def _receive_from_openai(self, twilio_ws: WebSocket, openai_ws, state: _BridgeState) -> None:
        try:
            async for message in openai_ws:
                try:
                    response = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from OpenAI: %s", message)
                    continue

                response_type = response.get("type")

                if response_type == "error":
                    error_msg = response.get("error", {}).get("message", "Unknown error")
                    logger.error("OpenAI error: %s", error_msg)
                    state.response_in_progress = False
                    continue

                if response_type == "response.created":
                    state.response_in_progress = True
                    logger.info("Response generation started")

                if response_type == "response.audio.delta":
                    audio_payload = response.get("delta")
                    if not audio_payload:
                        logger.warning("Audio delta received without payload")
                        continue
                    if not state.stream_sid:
                        logger.warning("Missing stream SID; cannot send audio")
                        continue
                    await twilio_ws.send_json(
                        {
                            "event": "media",
                            "streamSid": state.stream_sid,
                            "media": {"payload": audio_payload},
                        }
                    )
                    continue

                if response_type == "response.text.delta":
                    logger.debug("Text response: %s", response.get("text", ""))

                if response_type == "response.done":
                    state.response_in_progress = False
                    logger.info("Response complete")

                if response_type == "response.function_call_arguments.done":
                    if response.get("name") == "schedule_meeting":
                        await self._handle_schedule_meeting(openai_ws, response)
        except ConnectionClosed:
            logger.warning("OpenAI WebSocket closed")
        except Exception as exc:
            logger.exception("Error receiving from OpenAI: %s", exc)

    async def _handle_schedule_meeting(self, openai_ws, response: dict) -> None:
        try:
            args = json.loads(response.get("arguments", "{}"))
            user_request = args.get("user_request")
            if not user_request:
                logger.warning("schedule_meeting called without user_request")
                return

            result_text = await asyncio.to_thread(self.schedule_meeting, user_request)

            await openai_ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": response.get("call_id"),
                            "output": result_text,
                        },
                    }
                )
            )
            await asyncio.sleep(0.5)
            await openai_ws.send(json.dumps({"type": "response.create"}))
        except Exception as exc:
            logger.exception("Error handling schedule_meeting: %s", exc)

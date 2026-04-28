import logging
import re

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.core.config import get_settings
from app.services.openai_realtime import RealtimeBridge
from app.services.scheduler import schedule_meeting_tool

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_e164(raw: str) -> str:
    cleaned = re.sub(r"[^0-9+]", "", raw)
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    if cleaned.startswith("+"):
        return cleaned
    return f"+{cleaned}" if cleaned else ""


@router.api_route("/voice/incoming", methods=["GET", "POST"])
async def handle_incoming_call(request: Request) -> Response:
    scraped_data = request.query_params.get("data", "No data provided.")
    settings = get_settings()
    caller = None
    callee = None
    if request.method == "POST":
        form = await request.form()
        caller = form.get("From")
        callee = form.get("To") or form.get("Called")
    if not caller:
        caller = request.query_params.get("from") or request.query_params.get("caller")
    if not callee:
        callee = request.query_params.get("to") or request.query_params.get("called")

    user_id = caller
    if settings.twilio_phone_number and caller:
        twilio_number = _normalize_e164(settings.twilio_phone_number)
        if twilio_number and _normalize_e164(str(caller)) == twilio_number and callee:
            user_id = callee
    elif not user_id and callee:
        user_id = callee

    if user_id:
        user_id = _normalize_e164(str(user_id))

    # Prefer the header set by reverse-proxies (ngrok, nginx, etc.)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        logger.error("Missing host header in incoming call request")
        return Response(status_code=400, content="Missing host header")

    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=f"wss://{host}/media-stream")
    stream.parameter(name="scraped_data", value=scraped_data)
    if user_id:
        stream.parameter(name="user_id", value=str(user_id))
    response.append(connect)

    return Response(content=str(response), media_type="application/xml")


@router.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    bridge = RealtimeBridge(settings=settings, schedule_meeting=schedule_meeting_tool)

    try:
        await bridge.run(websocket)
    except WebSocketDisconnect:
        logger.info("Twilio WebSocket disconnected")

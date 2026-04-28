import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.core.config import get_settings
from app.services.openai_realtime import RealtimeBridge
from app.services.scheduler import schedule_meeting_tool

logger = logging.getLogger(__name__)
router = APIRouter()


@router.api_route("/voice/incoming", methods=["GET", "POST"])
async def handle_incoming_call(request: Request) -> Response:
    params = request.query_params
    scraped_data = params.get("data", "No data provided.")

    host = request.headers.get("x-forwarded-host", request.headers.get("host"))
    if not host:
        logger.error("Missing host header in incoming call request")
        return Response(status_code=400, content="Missing host header")

    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=f"wss://{host}/media-stream")
    stream.parameter(name="scraped_data", value=scraped_data)
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

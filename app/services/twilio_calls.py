from __future__ import annotations

import logging
import urllib.parse

from twilio.rest import Client

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def initiate_call(phone_number: str, scraped_content: str) -> str:
    """Initiate an outbound Twilio call pre-loaded with *scraped_content*."""
    settings = get_settings()

    if not settings.server_host:
        raise ValueError("SERVER_HOST is missing from environment variables")
    if not all(
        [settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_phone_number]
    ):
        raise ValueError("One or more Twilio credentials are missing from environment variables")

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    encoded_data = urllib.parse.quote(scraped_content)
    voice_url = f"https://{settings.server_host}/voice/incoming?data={encoded_data}"

    logger.info("Initiating call to %s", phone_number)
    call = client.calls.create(
        to=phone_number,
        from_=settings.twilio_phone_number,
        url=voice_url,
    )
    logger.info("Call SID: %s", call.sid)
    return call.sid

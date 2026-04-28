import logging
import urllib.parse

from twilio.rest import Client

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def initiate_call(phone_number: str, scraped_content: str) -> str:
    settings = get_settings()

    if not settings.server_host:
        raise ValueError("SERVER_HOST missing in environment")
    if not settings.twilio_account_sid or not settings.twilio_auth_token or not settings.twilio_phone_number:
        raise ValueError("Twilio credentials missing in environment")

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    encoded_data = urllib.parse.quote(scraped_content)
    voice_url = f"https://{settings.server_host}/voice/incoming?data={encoded_data}"

    logger.info("Calling %s", phone_number)
    call = client.calls.create(
        to=phone_number,
        from_=settings.twilio_phone_number,
        url=voice_url,
    )
    return call.sid

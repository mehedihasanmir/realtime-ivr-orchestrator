from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from functools import lru_cache
from typing import Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

_WEEKDAY_NAMES = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _require_env(name: str) -> str:
    value = _get_env(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_int(name: str, default: int) -> int:
    value = _get_env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer for {name}: {value!r}") from exc


def _get_time(name: str, default: str) -> time:
    value = _get_env(name, default)
    try:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))
    except Exception as exc:
        raise RuntimeError(f"Invalid HH:MM time for {name}: {value!r}") from exc


def _get_business_days() -> Tuple[int, ...]:
    """Parse BUSINESS_DAYS (e.g. 'sun,mon,tue,wed,thu') into weekday numbers (Mon=0)."""
    raw = _get_env("BUSINESS_DAYS", "sun,mon,tue,wed,thu")
    days = []
    for part in raw.split(","):
        key = part.strip().lower()[:3]
        if key not in _WEEKDAY_NAMES:
            raise RuntimeError(f"Invalid day name in BUSINESS_DAYS: {part!r}")
        days.append(_WEEKDAY_NAMES[key])
    return tuple(sorted(set(days)))


def _get_modalities() -> Tuple[str, ...]:
    raw = _get_env("OPENAI_MODALITIES")
    if raw:
        parts = [item.strip() for item in raw.split(",") if item.strip()]
        if parts:
            return tuple(parts)
    return ("audio", "text")


def _get_realtime_url() -> str:
    url = _get_env("OPENAI_REALTIME_URL")
    if url:
        return url
    model = _get_env("OPENAI_REALTIME_MODEL", "gpt-realtime")
    return f"wss://api.openai.com/v1/realtime?model={model}"


@dataclass(frozen=True)
class Settings:
    # OpenAI
    openai_api_key: str
    openai_realtime_url: str
    openai_voice: str
    openai_max_tokens: int
    openai_modalities: Tuple[str, ...]
    openai_input_audio_format: str
    openai_output_audio_format: str
    openai_turn_detection_type: str

    # Barge-in tuning
    barge_in_rms_threshold: int
    barge_in_trigger_frames: int

    # Twilio
    twilio_account_sid: Optional[str]
    twilio_auth_token: Optional[str]
    twilio_phone_number: Optional[str]
    server_host: Optional[str]

    # Database
    database_url: str

    # Business calendar / booking rules
    business_name: str
    business_timezone: str
    business_open: time
    business_close: time
    business_days: Tuple[int, ...]
    slot_minutes: int

    # Google Calendar sync (service account)
    google_service_account_file: str
    business_calendar_id: Optional[str]

    # Email (Gmail SMTP)
    gmail_address: Optional[str]
    gmail_app_password: Optional[str]

    # Admin dashboard
    admin_api_token: Optional[str]

    log_level: str

    @property
    def openai_turn_detection(self) -> dict:
        """Return the turn-detection dict expected by the OpenAI session API."""
        return {"type": self.openai_turn_detection_type}

    @property
    def public_base_url(self) -> Optional[str]:
        return f"https://{self.server_host}" if self.server_host else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        openai_api_key=_require_env("OPENAI_API_KEY"),
        openai_realtime_url=_get_realtime_url(),
        openai_voice=_get_env("OPENAI_VOICE", "alloy"),
        openai_max_tokens=_get_int("OPENAI_MAX_TOKENS", 4096),
        openai_modalities=_get_modalities(),
        openai_input_audio_format=_get_env("OPENAI_INPUT_AUDIO_FORMAT", "g711_ulaw"),
        openai_output_audio_format=_get_env("OPENAI_OUTPUT_AUDIO_FORMAT", "g711_ulaw"),
        openai_turn_detection_type=_get_env("OPENAI_TURN_DETECTION_TYPE", "server_vad"),
        barge_in_rms_threshold=_get_int("BARGE_IN_RMS_THRESHOLD", 120),
        barge_in_trigger_frames=_get_int("BARGE_IN_TRIGGER_FRAMES", 1),
        twilio_account_sid=_get_env("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=_get_env("TWILIO_AUTH_TOKEN"),
        twilio_phone_number=_get_env("TWILIO_PHONE_NUMBER"),
        server_host=_get_env("SERVER_HOST"),
        database_url=_get_env("DATABASE_URL", "sqlite:///./voice_agent.db"),
        business_name=_get_env("BUSINESS_NAME", "Our Office"),
        business_timezone=_get_env("BUSINESS_TIMEZONE", "Asia/Dhaka"),
        business_open=_get_time("BUSINESS_OPEN", "10:00"),
        business_close=_get_time("BUSINESS_CLOSE", "18:00"),
        business_days=_get_business_days(),
        slot_minutes=_get_int("SLOT_MINUTES", 30),
        google_service_account_file=_get_env(
            "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"
        ),
        business_calendar_id=_get_env("BUSINESS_CALENDAR_ID"),
        gmail_address=_get_env("GMAIL_ADDRESS"),
        gmail_app_password=_get_env("GMAIL_APP_PASSWORD"),
        admin_api_token=_get_env("ADMIN_API_TOKEN"),
        log_level=_get_env("LOG_LEVEL", "INFO"),
    )

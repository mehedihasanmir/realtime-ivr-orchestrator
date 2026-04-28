from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from typing import Optional, Tuple

from dotenv import load_dotenv

load_dotenv()


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
        raise RuntimeError(f"Invalid integer for {name}: {value}") from exc


def _get_float(name: str, default: float) -> float:
    value = _get_env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid float for {name}: {value}") from exc


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
    model = _get_env("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")
    return f"wss://api.openai.com/v1/realtime?model={model}"


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_realtime_url: str
    openai_voice: str
    openai_temperature: float
    openai_max_tokens: int
    openai_modalities: Tuple[str, ...]
    openai_input_audio_format: str
    openai_output_audio_format: str
    openai_turn_detection: dict
    twilio_account_sid: Optional[str]
    twilio_auth_token: Optional[str]
    twilio_phone_number: Optional[str]
    server_host: Optional[str]
    google_credentials_path: str
    log_level: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        openai_api_key=_require_env("OPENAI_API_KEY"),
        openai_realtime_url=_get_realtime_url(),
        openai_voice=_get_env("OPENAI_VOICE", "alloy"),
        openai_temperature=_get_float("OPENAI_TEMPERATURE", 0.8),
        openai_max_tokens=_get_int("OPENAI_MAX_TOKENS", 4096),
        openai_modalities=_get_modalities(),
        openai_input_audio_format=_get_env("OPENAI_INPUT_AUDIO_FORMAT", "g711_ulaw"),
        openai_output_audio_format=_get_env("OPENAI_OUTPUT_AUDIO_FORMAT", "g711_ulaw"),
        openai_turn_detection={"type": "server_vad"},
        twilio_account_sid=_get_env("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=_get_env("TWILIO_AUTH_TOKEN"),
        twilio_phone_number=_get_env("TWILIO_PHONE_NUMBER"),
        server_host=_get_env("SERVER_HOST"),
        google_credentials_path=_get_env("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json"),
        log_level=_get_env("LOG_LEVEL", "INFO"),
    )

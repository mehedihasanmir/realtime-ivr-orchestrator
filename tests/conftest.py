"""Shared test fixtures.

Every test gets a fresh SQLite database in a temp directory and deterministic
business settings. Twilio/Gmail/Calendar credentials are stripped so no test
ever touches an external service.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

BUSINESS_TZ = ZoneInfo("Asia/Dhaka")
ADMIN_TOKEN = "test-admin-token"

# Weekday numbers (Mon=0): business days are Sun-Thu.
_OPEN_WEEKDAYS = {6, 0, 1, 2, 3}
_CLOSED_WEEKDAY = 4  # Friday


@pytest.fixture(autouse=True)
def test_env(tmp_path, monkeypatch):
    """Isolate settings + database for every test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_API_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("SERVER_HOST", "test.example.com")
    monkeypatch.setenv("BUSINESS_NAME", "Test Office")
    monkeypatch.setenv("BUSINESS_TIMEZONE", "Asia/Dhaka")
    monkeypatch.setenv("BUSINESS_DAYS", "sun,mon,tue,wed,thu")
    monkeypatch.setenv("BUSINESS_OPEN", "10:00")
    monkeypatch.setenv("BUSINESS_CLOSE", "18:00")
    monkeypatch.setenv("SLOT_MINUTES", "30")
    # Make sure no external service is ever contacted from tests.
    for var in (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_PHONE_NUMBER",
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
        "BUSINESS_CALENDAR_ID",
    ):
        monkeypatch.delenv(var, raising=False)

    from app.core import config
    import app.db.database as database

    config.get_settings.cache_clear()
    database._engine = None
    database._SessionLocal = None

    from app.db import init_db

    init_db()
    yield
    config.get_settings.cache_clear()
    database._engine = None
    database._SessionLocal = None


@pytest.fixture()
def settings():
    from app.core.config import get_settings

    return get_settings()


@pytest.fixture()
def booking_service(settings):
    from app.services.booking import BookingService

    return BookingService(settings)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def next_open_day_at(hour: int, minute: int = 0) -> datetime:
    """Return the next business day (starting tomorrow) at the given local time."""
    day = datetime.now(BUSINESS_TZ) + timedelta(days=1)
    while day.weekday() not in _OPEN_WEEKDAYS:
        day += timedelta(days=1)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def next_closed_day_at(hour: int) -> datetime:
    """Return the next Friday (closed day) at the given local time."""
    day = datetime.now(BUSINESS_TZ) + timedelta(days=1)
    while day.weekday() != _CLOSED_WEEKDAY:
        day += timedelta(days=1)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def iso_local(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")

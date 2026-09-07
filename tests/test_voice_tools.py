"""Tests for the tools exposed to the realtime voice agent."""

from __future__ import annotations

import pytest

from tests.conftest import iso_local, next_open_day_at

PHONE = "+8801700000009"


@pytest.fixture()
def registry(settings):
    from app.services.voice_tools import VoiceToolRegistry

    return VoiceToolRegistry(settings)


def test_schemas_expose_expected_tools(registry):
    names = [tool["name"] for tool in registry.schemas]
    assert names == ["check_availability", "book_meeting", "request_callback"]


def test_unknown_tool_returns_error(registry):
    assert "unknown tool" in registry.dispatch("does_not_exist", {}, PHONE)


def test_handler_exception_is_contained(registry, monkeypatch):
    def boom(_args, _phone):
        raise RuntimeError("boom")

    monkeypatch.setitem(registry._handlers, "check_availability", boom)
    result = registry.dispatch("check_availability", {}, PHONE)
    assert "request_callback" in result  # graceful fallback instruction


def test_full_booking_conversation_flow(registry):
    when = iso_local(next_open_day_at(11))

    free = registry.dispatch("check_availability", {"requested_time": when}, PHONE)
    assert "FREE" in free

    booked = registry.dispatch(
        "book_meeting",
        {"requested_time": when, "name": "Flow User", "email": "flow@example.com"},
        PHONE,
    )
    assert "Booked!" in booked

    taken = registry.dispatch("check_availability", {"requested_time": when}, PHONE)
    assert "Not available" in taken


def test_book_meeting_requires_caller_phone(registry):
    result = registry.dispatch(
        "book_meeting",
        {"requested_time": iso_local(next_open_day_at(11)), "name": "X", "email": "x@y.z"},
        None,
    )
    assert "Error" in result


def test_invalid_time_is_reported(registry):
    result = registry.dispatch(
        "check_availability", {"requested_time": "gibberish"}, PHONE
    )
    assert "Not available" in result


def test_request_callback_saves_record(registry):
    from sqlalchemy import select

    from app.db import CallbackRequest, session_scope

    result = registry.dispatch("request_callback", {"reason": "wants a human"}, PHONE)
    assert "Callback saved" in result

    with session_scope() as session:
        callback = session.execute(select(CallbackRequest)).scalar_one()
        assert callback.reason == "wants a human"
        assert callback.customer.phone == PHONE

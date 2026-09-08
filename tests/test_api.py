"""API tests: admin auth, admin endpoints, and the public cancel flow."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ADMIN_TOKEN, iso_local, next_open_day_at

PHONE = "+8801700000042"
AUTH = {"X-Admin-Token": ADMIN_TOKEN}


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _create_booking(settings):
    from app.services.booking import BookingService

    service = BookingService(settings)
    result = service.book_meeting(
        requested_iso=iso_local(next_open_day_at(11)),
        phone=PHONE,
        name="Api User",
        email="api@example.com",
    )
    assert result.success
    return result


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_pages_are_served(client):
    assert client.get("/admin").status_code == 200
    assert client.get("/cancel/any-token").status_code == 200


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------

def test_admin_requires_token(client):
    assert client.get("/api/admin/stats").status_code == 401
    assert (
        client.get("/api/admin/stats", headers={"X-Admin-Token": "wrong"}).status_code
        == 401
    )


def test_admin_stats_and_bookings(client, settings):
    _create_booking(settings)

    stats = client.get("/api/admin/stats", headers=AUTH).json()
    assert stats["upcoming_bookings"] == 1
    assert stats["total_customers"] == 1

    bookings = client.get("/api/admin/bookings", headers=AUTH).json()
    assert len(bookings) == 1
    assert bookings[0]["customer_phone"] == PHONE
    assert bookings[0]["status"] == "confirmed"


def test_admin_cancel_booking(client, settings):
    booked = _create_booking(settings)

    response = client.post(
        f"/api/admin/bookings/{booked.booking_id}/cancel", headers=AUTH
    )
    assert response.status_code == 200

    bookings = client.get("/api/admin/bookings", headers=AUTH).json()
    assert bookings[0]["status"] == "cancelled"


def test_admin_callback_complete(client, settings):
    from app.services.booking import BookingService

    BookingService(settings).create_callback_request(phone=PHONE, reason="test")

    callbacks = client.get("/api/admin/callbacks", headers=AUTH).json()
    assert len(callbacks) == 1
    assert callbacks[0]["status"] == "pending"

    response = client.post(
        f"/api/admin/callbacks/{callbacks[0]['id']}/complete", headers=AUTH
    )
    assert response.status_code == 200

    callbacks = client.get("/api/admin/callbacks", headers=AUTH).json()
    assert callbacks[0]["status"] == "completed"


def test_admin_outbound_call_validation(client):
    # Requires auth.
    assert client.post("/api/admin/calls", json={"phone": "+8801700000000"}).status_code == 401

    # Invalid phone format.
    bad = client.post(
        "/api/admin/calls", json={"phone": "not-a-number"}, headers=AUTH
    )
    assert bad.status_code == 400
    assert "E.164" in bad.json()["detail"]

    # Valid phone but Twilio is not configured in tests -> clean 400, not a crash.
    response = client.post(
        "/api/admin/calls", json={"phone": "+8801700000000"}, headers=AUTH
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Public cancel flow
# ---------------------------------------------------------------------------

def test_public_unknown_token_is_404(client):
    assert client.get("/api/public/bookings/no-such-token").status_code == 404


def test_public_cancel_flow(client, settings):
    booked = _create_booking(settings)
    token = booked.cancel_token

    details = client.get(f"/api/public/bookings/{token}")
    assert details.status_code == 200
    assert details.json()["customer_name"] == "Api User"
    assert details.json()["status"] == "confirmed"

    response = client.post(f"/api/public/bookings/{token}/cancel")
    assert response.status_code == 200

    # Second cancel must fail cleanly.
    assert client.post(f"/api/public/bookings/{token}/cancel").status_code == 400
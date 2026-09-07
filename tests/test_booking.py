"""Unit tests for the booking engine (availability, booking, cancel, reminders)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from tests.conftest import iso_local, next_closed_day_at, next_open_day_at

PHONE = "+8801700000001"


def _book(service, when, name="Test User", email="test@example.com", phone=PHONE):
    return service.book_meeting(
        requested_iso=iso_local(when), phone=phone, name=name, email=email
    )


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def test_open_slot_is_available(booking_service):
    result = booking_service.check_availability(iso_local(next_open_day_at(11)))
    assert result.available is True


def test_outside_business_hours_rejected(booking_service):
    result = booking_service.check_availability(iso_local(next_open_day_at(20)))
    assert result.available is False
    assert "business hours" in result.reason


def test_closed_day_rejected(booking_service):
    result = booking_service.check_availability(iso_local(next_closed_day_at(11)))
    assert result.available is False
    assert result.alternatives, "should suggest alternative slots"
    # Every suggested alternative must be on a business day.
    assert all(alt.weekday() in {6, 0, 1, 2, 3} for alt in result.alternatives)


def test_past_time_rejected(booking_service):
    yesterday = datetime.now() - timedelta(days=1)
    result = booking_service.check_availability(iso_local(yesterday))
    assert result.available is False
    assert "past" in result.reason


def test_invalid_time_string_rejected(booking_service):
    result = booking_service.check_availability("next tuesday sometime")
    assert result.available is False


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------

def test_booking_creates_customer_and_booking(booking_service):
    from app.db import Booking, Customer, session_scope

    when = next_open_day_at(11)
    result = _book(booking_service, when)

    assert result.success is True
    assert result.cancel_token
    assert result.start_local.hour == 11

    with session_scope() as session:
        customer = session.execute(
            select(Customer).where(Customer.phone == PHONE)
        ).scalar_one()
        assert customer.name == "Test User"
        assert customer.email == "test@example.com"
        booking = session.execute(select(Booking)).scalar_one()
        assert booking.customer_id == customer.id


def test_double_booking_rejected_with_alternatives(booking_service):
    when = next_open_day_at(11)
    assert _book(booking_service, when).success is True

    second = _book(booking_service, when, phone="+8801700000002")
    assert second.success is False
    assert second.alternatives, "should offer alternative slots"


def test_rebooking_same_customer_updates_profile(booking_service):
    from app.db import Customer, session_scope

    _book(booking_service, next_open_day_at(11), name="Old Name")
    _book(booking_service, next_open_day_at(14), name="New Name", email="new@example.com")

    with session_scope() as session:
        customers = session.execute(select(Customer)).scalars().all()
        assert len(customers) == 1
        assert customers[0].name == "New Name"
        assert customers[0].email == "new@example.com"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

def test_cancel_frees_the_slot(booking_service):
    when = next_open_day_at(11)
    booked = _book(booking_service, when)

    cancelled = booking_service.cancel_booking(cancel_token=booked.cancel_token)
    assert cancelled.success is True

    result = booking_service.check_availability(iso_local(when))
    assert result.available is True


def test_cancel_twice_fails(booking_service):
    booked = _book(booking_service, next_open_day_at(11))
    assert booking_service.cancel_booking(cancel_token=booked.cancel_token).success
    again = booking_service.cancel_booking(cancel_token=booked.cancel_token)
    assert again.success is False
    assert "already" in again.message


def test_cancel_unknown_token_fails(booking_service):
    result = booking_service.cancel_booking(cancel_token="no-such-token")
    assert result.success is False


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

def _insert_booking_starting_in(minutes: int) -> int:
    """Insert a confirmed booking directly, bypassing business-hours checks."""
    from app.db import Booking, Customer, session_scope

    start = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=minutes)
    with session_scope() as session:
        customer = Customer(phone=PHONE, name="Reminder User", email="r@example.com")
        session.add(customer)
        session.flush()
        booking = Booking(
            customer_id=customer.id,
            start_time_utc=start,
            end_time_utc=start + timedelta(minutes=30),
        )
        session.add(booking)
        session.flush()
        return booking.id


def test_reminder_claimed_exactly_once(booking_service):
    booking_id = _insert_booking_starting_in(30)

    due = booking_service.claim_due_reminders()
    assert [item["booking_id"] for item in due] == [booking_id]
    assert due[0]["email"] == "r@example.com"

    assert booking_service.claim_due_reminders() == []


def test_reminder_not_due_outside_window(booking_service):
    _insert_booking_starting_in(120)  # 2 hours away
    assert booking_service.claim_due_reminders() == []

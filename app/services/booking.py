"""Booking engine: the database is the source of truth for availability.

All public methods accept/return datetimes in the business timezone; storage
is naive UTC. Google Calendar sync and notifications are handled by callers
(see voice_tools) so this module stays free of I/O side effects other than
the database and calendar sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import Settings
from app.db import Booking, BookingStatus, CallbackRequest, Customer, session_scope
from app.services.business_calendar import BusinessCalendar

logger = logging.getLogger(__name__)


@dataclass
class AvailabilityResult:
    available: bool
    reason: str = ""
    requested_local: Optional[datetime] = None
    alternatives: List[datetime] = field(default_factory=list)


@dataclass
class BookingResult:
    success: bool
    message: str
    booking_id: Optional[int] = None
    cancel_token: Optional[str] = None
    start_local: Optional[datetime] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    alternatives: List[datetime] = field(default_factory=list)


class BookingService:
    def __init__(self, settings: Settings, calendar: Optional[BusinessCalendar] = None) -> None:
        self._settings = settings
        self._calendar = calendar or BusinessCalendar(settings)
        self._tz = ZoneInfo(settings.business_timezone)
        self._slot = timedelta(minutes=settings.slot_minutes)

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------

    def now_local(self) -> datetime:
        return datetime.now(self._tz)

    def parse_local(self, iso_string: str) -> datetime:
        """Parse an ISO-8601 string; naive values are assumed to be business-local."""
        parsed = datetime.fromisoformat(iso_string.strip())
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=self._tz)
        return parsed.astimezone(self._tz)

    def _to_utc_naive(self, local_dt: datetime) -> datetime:
        return local_dt.astimezone(timezone.utc).replace(tzinfo=None)

    def to_local(self, utc_naive: datetime) -> datetime:
        return utc_naive.replace(tzinfo=timezone.utc).astimezone(self._tz)

    def _align_to_slot(self, local_dt: datetime) -> datetime:
        """Snap a time down to the nearest slot boundary within the day."""
        day_open = local_dt.replace(
            hour=self._settings.business_open.hour,
            minute=self._settings.business_open.minute,
            second=0,
            microsecond=0,
        )
        if local_dt <= day_open:
            return day_open
        offset = (local_dt - day_open) % self._slot
        return local_dt - offset

    def _within_business_hours(self, start_local: datetime) -> bool:
        end_local = start_local + self._slot
        open_t = self._settings.business_open
        close_t = self._settings.business_close
        if start_local.weekday() not in self._settings.business_days:
            return False
        if start_local.timetz().replace(tzinfo=None) < time(open_t.hour, open_t.minute):
            return False
        end_time = (end_local - timedelta(microseconds=1)).time()
        if end_local.date() != start_local.date():
            return False
        if end_time > time(close_t.hour, close_t.minute) and end_local.time() != time(
            close_t.hour, close_t.minute
        ):
            return False
        return True

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def _is_slot_taken(self, session, start_utc: datetime, end_utc: datetime) -> bool:
        stmt = select(Booking.id).where(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_time_utc < end_utc,
            Booking.end_time_utc > start_utc,
        )
        return session.execute(stmt).first() is not None

    def _next_free_slots(
        self, session, from_local: datetime, count: int = 3, days_ahead: int = 14
    ) -> List[datetime]:
        slots: List[datetime] = []
        cursor = self._align_to_slot(max(from_local, self.now_local()))
        horizon = cursor + timedelta(days=days_ahead)
        while cursor < horizon and len(slots) < count:
            if self._within_business_hours(cursor) and cursor > self.now_local():
                start_utc = self._to_utc_naive(cursor)
                if not self._is_slot_taken(session, start_utc, start_utc + self._slot):
                    slots.append(cursor)
            cursor += self._slot
            # Jump past closed hours quickly.
            if cursor.time() >= self._settings.business_close:
                cursor = (cursor + timedelta(days=1)).replace(
                    hour=self._settings.business_open.hour,
                    minute=self._settings.business_open.minute,
                    second=0,
                    microsecond=0,
                )
        return slots

    def check_availability(self, requested_iso: str) -> AvailabilityResult:
        try:
            requested_local = self._align_to_slot(self.parse_local(requested_iso))
        except ValueError:
            return AvailabilityResult(
                available=False,
                reason="I could not understand that date and time.",
            )

        with session_scope() as session:
            if requested_local <= self.now_local():
                return AvailabilityResult(
                    available=False,
                    reason="That time is in the past.",
                    requested_local=requested_local,
                    alternatives=self._next_free_slots(session, self.now_local()),
                )
            if not self._within_business_hours(requested_local):
                return AvailabilityResult(
                    available=False,
                    reason="That time is outside business hours.",
                    requested_local=requested_local,
                    alternatives=self._next_free_slots(session, requested_local),
                )
            start_utc = self._to_utc_naive(requested_local)
            if self._is_slot_taken(session, start_utc, start_utc + self._slot):
                return AvailabilityResult(
                    available=False,
                    reason="That slot is already booked.",
                    requested_local=requested_local,
                    alternatives=self._next_free_slots(session, requested_local),
                )
            return AvailabilityResult(available=True, requested_local=requested_local)

    # ------------------------------------------------------------------
    # Booking
    # ------------------------------------------------------------------

    def _upsert_customer(
        self, session, phone: str, name: Optional[str], email: Optional[str]
    ) -> Customer:
        customer = session.execute(
            select(Customer).where(Customer.phone == phone)
        ).scalar_one_or_none()
        if customer is None:
            customer = Customer(phone=phone, name=name, email=email)
            session.add(customer)
            session.flush()
        else:
            if name:
                customer.name = name
            if email:
                customer.email = email
        return customer

    def book_meeting(
        self, *, requested_iso: str, phone: str, name: str, email: str
    ) -> BookingResult:
        availability = self.check_availability(requested_iso)
        if not availability.available:
            return BookingResult(
                success=False,
                message=availability.reason,
                alternatives=availability.alternatives,
            )

        start_local = availability.requested_local
        start_utc = self._to_utc_naive(start_local)
        end_utc = start_utc + self._slot

        with session_scope() as session:
            # Re-check inside the transaction to close the race window.
            if self._is_slot_taken(session, start_utc, end_utc):
                return BookingResult(
                    success=False,
                    message="That slot was just booked by someone else.",
                    alternatives=self._next_free_slots(session, start_local),
                )
            customer = self._upsert_customer(session, phone, name, email)
            booking = Booking(
                customer_id=customer.id,
                start_time_utc=start_utc,
                end_time_utc=end_utc,
            )
            session.add(booking)
            session.flush()

            event_id = self._calendar.create_event(
                summary=f"Meeting: {customer.name or phone}",
                description=(
                    f"Booked via AI voice agent.\n"
                    f"Customer: {customer.name}\nPhone: {phone}\nEmail: {email}"
                ),
                start_local=start_local,
                end_local=start_local + self._slot,
            )
            if event_id:
                booking.gcal_event_id = event_id

            return BookingResult(
                success=True,
                message="Booked successfully.",
                booking_id=booking.id,
                cancel_token=booking.cancel_token,
                start_local=start_local,
                customer_name=customer.name,
                customer_email=customer.email,
            )

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel_booking(
        self, *, booking_id: Optional[int] = None, cancel_token: Optional[str] = None
    ) -> BookingResult:
        with session_scope() as session:
            stmt = select(Booking)
            if booking_id is not None:
                stmt = stmt.where(Booking.id == booking_id)
            elif cancel_token:
                stmt = stmt.where(Booking.cancel_token == cancel_token)
            else:
                return BookingResult(success=False, message="No booking reference given.")

            booking = session.execute(stmt).scalar_one_or_none()
            if booking is None:
                return BookingResult(success=False, message="Booking not found.")
            if booking.status == BookingStatus.CANCELLED:
                return BookingResult(success=False, message="Booking is already cancelled.")

            booking.status = BookingStatus.CANCELLED
            customer = booking.customer
            if booking.gcal_event_id:
                self._calendar.delete_event(booking.gcal_event_id)

            return BookingResult(
                success=True,
                message="Booking cancelled.",
                booking_id=booking.id,
                start_local=self.to_local(booking.start_time_utc),
                customer_name=customer.name,
                customer_email=customer.email,
            )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def create_callback_request(self, *, phone: str, reason: Optional[str]) -> int:
        with session_scope() as session:
            customer = self._upsert_customer(session, phone, None, None)
            callback = CallbackRequest(customer_id=customer.id, reason=reason)
            session.add(callback)
            session.flush()
            return callback.id

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------

    def claim_due_reminders(self) -> List[dict]:
        """Mark bookings starting within the next hour as reminded and return them.

        Marking happens in the same transaction as the read so each reminder is
        claimed exactly once even if the loop overlaps.
        """
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        window_end = now_utc + timedelta(hours=1)
        due: List[dict] = []
        with session_scope() as session:
            stmt = select(Booking).where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.reminder_sent.is_(False),
                Booking.start_time_utc > now_utc,
                Booking.start_time_utc <= window_end,
            )
            for booking in session.execute(stmt).scalars():
                booking.reminder_sent = True
                customer = booking.customer
                due.append(
                    {
                        "booking_id": booking.id,
                        "start_local": self.to_local(booking.start_time_utc),
                        "name": customer.name or "there",
                        "email": customer.email,
                    }
                )
        return due

"""Background loop that emails customers ~1 hour before their meeting."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings
from app.services.booking import BookingService
from app.services.notifications import EmailService

logger = logging.getLogger(__name__)

_POLL_SECONDS = 60


def _process_due_reminders(booking: BookingService, email: EmailService) -> None:
    for item in booking.claim_due_reminders():
        if not item["email"]:
            logger.warning(
                "Booking %s has no customer email; skipping reminder", item["booking_id"]
            )
            continue
        email.send_booking_reminder(
            to_email=item["email"],
            customer_name=item["name"],
            start_local=item["start_local"],
        )
        logger.info("Sent 1-hour reminder for booking %s", item["booking_id"])


async def reminder_loop(settings: Settings) -> None:
    booking = BookingService(settings)
    email = EmailService(settings)
    logger.info("Reminder loop started (every %ss)", _POLL_SECONDS)
    while True:
        try:
            await asyncio.to_thread(_process_due_reminders, booking, email)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Reminder loop iteration failed: %s", exc)
        await asyncio.sleep(_POLL_SECONDS)

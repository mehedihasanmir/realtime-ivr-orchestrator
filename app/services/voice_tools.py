"""Tools exposed to the realtime voice agent.

Each handler is a synchronous function (the bridge runs them in a worker
thread) that receives the model's arguments plus the caller's phone number
and returns a short, speech-friendly string for the model to relay.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

from app.core.config import Settings
from app.services.booking import BookingService
from app.services.notifications import EmailService, SmsService

logger = logging.getLogger(__name__)

_SPOKEN_TIME_FORMAT = "%A %d %B at %I:%M %p"


def _spoken(dt_local: datetime) -> str:
    return dt_local.strftime(_SPOKEN_TIME_FORMAT)


def _spoken_alternatives(alternatives: List[datetime]) -> str:
    if not alternatives:
        return ""
    listed = "; ".join(_spoken(slot) for slot in alternatives)
    return f" Free slots nearby: {listed}."


class VoiceToolRegistry:
    """Bundles tool schemas with their handlers for the realtime bridge."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._booking = BookingService(settings)
        self._email = EmailService(settings)
        self._sms = SmsService(settings)
        self._handlers: Dict[str, Callable[[dict, Optional[str]], str]] = {
            "check_availability": self._check_availability,
            "book_meeting": self._book_meeting,
            "request_callback": self._request_callback,
        }

    # ------------------------------------------------------------------
    # Schemas (GA Realtime API function tool format)
    # ------------------------------------------------------------------

    @property
    def schemas(self) -> list:
        now_local = self._booking.now_local().strftime("%Y-%m-%dT%H:%M")
        return [
            {
                "type": "function",
                "name": "check_availability",
                "description": (
                    "Check whether a meeting slot is free before booking. "
                    f"The current local date-time is {now_local} "
                    f"({self._settings.business_timezone}). Always call this before "
                    "book_meeting."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "requested_time": {
                            "type": "string",
                            "description": (
                                "Requested start time as local ISO 8601, "
                                "e.g. 2026-09-08T16:00"
                            ),
                        }
                    },
                    "required": ["requested_time"],
                },
            },
            {
                "type": "function",
                "name": "book_meeting",
                "description": (
                    "Book a confirmed meeting slot. Only call after "
                    "check_availability said the slot is free AND the caller has "
                    "confirmed the exact time, their full name, and their email "
                    "address (read the email back to them first)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "requested_time": {
                            "type": "string",
                            "description": "Confirmed start time as local ISO 8601",
                        },
                        "name": {"type": "string", "description": "Caller's full name"},
                        "email": {
                            "type": "string",
                            "description": "Caller's email address for the confirmation",
                        },
                    },
                    "required": ["requested_time", "name", "email"],
                },
            },
            {
                "type": "function",
                "name": "request_callback",
                "description": (
                    "Use when you cannot help the caller, they explicitly ask for a "
                    "human, or booking keeps failing. Saves their number so a human "
                    "calls them back, and sends them a confirmation SMS."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Short summary of what the caller needs",
                        }
                    },
                    "required": ["reason"],
                },
            },
        ]

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, name: str, args: dict, caller_phone: Optional[str]) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return f"Error: unknown tool {name!r}."
        try:
            return handler(args, caller_phone)
        except Exception as exc:
            logger.exception("Tool %s failed: %s", name, exc)
            return (
                "Something went wrong on our side. Apologize and offer to have a "
                "team member call the customer back (use request_callback)."
            )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _check_availability(self, args: dict, caller_phone: Optional[str]) -> str:
        requested = args.get("requested_time", "")
        result = self._booking.check_availability(requested)
        if result.available:
            return (
                f"The slot on {_spoken(result.requested_local)} is FREE. "
                "Confirm the time with the caller, collect their name and email, "
                "then call book_meeting."
            )
        return f"Not available: {result.reason}{_spoken_alternatives(result.alternatives)}"

    def _book_meeting(self, args: dict, caller_phone: Optional[str]) -> str:
        if not caller_phone:
            return "Error: caller phone number is unknown; cannot book."
        result = self._booking.book_meeting(
            requested_iso=args.get("requested_time", ""),
            phone=caller_phone,
            name=args.get("name", "").strip(),
            email=args.get("email", "").strip(),
        )
        if not result.success:
            return (
                f"Booking failed: {result.message}"
                f"{_spoken_alternatives(result.alternatives)}"
            )

        cancel_url = None
        if self._settings.public_base_url and result.cancel_token:
            cancel_url = f"{self._settings.public_base_url}/cancel/{result.cancel_token}"
        if result.customer_email:
            self._email.send_booking_confirmation(
                to_email=result.customer_email,
                customer_name=result.customer_name or "there",
                start_local=result.start_local,
                cancel_url=cancel_url,
            )
        return (
            f"Booked! Meeting confirmed for {_spoken(result.start_local)}. "
            "A confirmation email with a cancellation link has been sent. "
            "Tell the caller and ask if they need anything else."
        )

    def _request_callback(self, args: dict, caller_phone: Optional[str]) -> str:
        if not caller_phone:
            return "Error: caller phone number is unknown; cannot save a callback."
        self._booking.create_callback_request(
            phone=caller_phone, reason=args.get("reason", "")
        )
        sms_sent = self._sms.send_callback_promise(caller_phone)
        suffix = " A confirmation SMS was also sent." if sms_sent else ""
        return (
            "Callback saved. Tell the caller a team member will call them back "
            f"shortly.{suffix}"
        )

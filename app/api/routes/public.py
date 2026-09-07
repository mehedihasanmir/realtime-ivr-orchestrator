"""Public endpoints used by the customer-facing cancel page."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.config import get_settings
from app.db import Booking, session_scope
from app.services.booking import BookingService
from app.services.notifications import EmailService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["public"])

_STATIC_DIR = Path(__file__).resolve().parents[3] / "static"


@router.get("/cancel/{token}")
async def cancel_page(token: str) -> FileResponse:
    return FileResponse(_STATIC_DIR / "cancel" / "index.html")


@router.get("/api/public/bookings/{token}")
def booking_details(token: str) -> dict:
    service = BookingService(get_settings())
    with session_scope() as session:
        booking = session.execute(
            select(Booking).where(Booking.cancel_token == token)
        ).scalar_one_or_none()
        if booking is None:
            raise HTTPException(status_code=404, detail="Booking not found")
        return {
            "customer_name": booking.customer.name,
            "start_time": service.to_local(booking.start_time_utc).isoformat(),
            "status": booking.status.value,
        }


@router.post("/api/public/bookings/{token}/cancel")
def cancel_booking(token: str) -> dict:
    settings = get_settings()
    service = BookingService(settings)
    result = service.cancel_booking(cancel_token=token)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)
    if result.customer_email:
        EmailService(settings).send_booking_cancellation(
            to_email=result.customer_email,
            customer_name=result.customer_name or "there",
            start_local=result.start_local,
        )
    return {"ok": True, "message": "Your booking has been cancelled."}

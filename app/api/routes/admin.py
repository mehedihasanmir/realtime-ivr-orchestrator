from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import (
    Booking,
    BookingStatus,
    CallbackRequest,
    CallbackStatus,
    Customer,
    session_scope,
)
from app.services.booking import BookingService
from app.services.notifications import EmailService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.admin_api_token:
        raise HTTPException(status_code=503, detail="ADMIN_API_TOKEN is not configured")
    if x_admin_token != settings.admin_api_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def _booking_dict(booking: Booking, service: BookingService) -> dict:
    return {
        "id": booking.id,
        "customer_name": booking.customer.name,
        "customer_phone": booking.customer.phone,
        "customer_email": booking.customer.email,
        "start_time": service.to_local(booking.start_time_utc).isoformat(),
        "end_time": service.to_local(booking.end_time_utc).isoformat(),
        "status": booking.status.value,
        "reminder_sent": booking.reminder_sent,
        "created_at": booking.created_at.isoformat() + "Z",
    }


@router.get("/stats", dependencies=[Depends(require_admin)])
def stats() -> dict:
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_scope() as session:
        upcoming = session.execute(
            select(func.count(Booking.id)).where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.start_time_utc >= now_utc,
            )
        ).scalar_one()
        today = session.execute(
            select(func.count(Booking.id)).where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.start_time_utc >= now_utc,
                Booking.start_time_utc < now_utc + timedelta(days=1),
            )
        ).scalar_one()
        customers = session.execute(select(func.count(Customer.id))).scalar_one()
        pending_callbacks = session.execute(
            select(func.count(CallbackRequest.id)).where(
                CallbackRequest.status == CallbackStatus.PENDING
            )
        ).scalar_one()
    return {
        "upcoming_bookings": upcoming,
        "next_24h_bookings": today,
        "total_customers": customers,
        "pending_callbacks": pending_callbacks,
    }


@router.get("/bookings", dependencies=[Depends(require_admin)])
def list_bookings(status: str | None = None, limit: int = 100) -> list[dict]:
    service = BookingService(get_settings())
    with session_scope() as session:
        stmt = select(Booking).order_by(Booking.start_time_utc.desc()).limit(limit)
        if status:
            try:
                stmt = stmt.where(Booking.status == BookingStatus(status))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Unknown status: {status}")
        bookings = session.execute(stmt).scalars().all()
        return [_booking_dict(b, service) for b in bookings]


@router.post("/bookings/{booking_id}/cancel", dependencies=[Depends(require_admin)])
def cancel_booking(booking_id: int) -> dict:
    settings = get_settings()
    service = BookingService(settings)
    result = service.cancel_booking(booking_id=booking_id)
    if not result.success:
        raise HTTPException(status_code=404, detail=result.message)
    if result.customer_email:
        EmailService(settings).send_booking_cancellation(
            to_email=result.customer_email,
            customer_name=result.customer_name or "there",
            start_local=result.start_local,
        )
    return {"ok": True, "message": result.message}


@router.get("/customers", dependencies=[Depends(require_admin)])
def list_customers(limit: int = 200) -> list[dict]:
    with session_scope() as session:
        customers = (
            session.execute(
                select(Customer).order_by(Customer.created_at.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "bookings": len(c.bookings),
                "created_at": c.created_at.isoformat() + "Z",
            }
            for c in customers
        ]


@router.get("/callbacks", dependencies=[Depends(require_admin)])
def list_callbacks(limit: int = 100) -> list[dict]:
    with session_scope() as session:
        callbacks = (
            session.execute(
                select(CallbackRequest)
                .order_by(CallbackRequest.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": cb.id,
                "customer_name": cb.customer.name,
                "customer_phone": cb.customer.phone,
                "reason": cb.reason,
                "status": cb.status.value,
                "created_at": cb.created_at.isoformat() + "Z",
            }
            for cb in callbacks
        ]


@router.post("/callbacks/{callback_id}/complete", dependencies=[Depends(require_admin)])
def complete_callback(callback_id: int) -> dict:
    with session_scope() as session:
        callback = session.get(CallbackRequest, callback_id)
        if callback is None:
            raise HTTPException(status_code=404, detail="Callback not found")
        callback.status = CallbackStatus.COMPLETED
    return {"ok": True}

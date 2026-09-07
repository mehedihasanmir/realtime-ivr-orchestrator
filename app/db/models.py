from __future__ import annotations

import enum
import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_cancel_token() -> str:
    return secrets.token_urlsafe(24)


class Base(DeclarativeBase):
    pass


class BookingStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class CallbackStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    bookings: Mapped[list["Booking"]] = relationship(back_populates="customer")
    callbacks: Mapped[list["CallbackRequest"]] = relationship(back_populates="customer")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    # Stored as naive UTC datetimes; converted to the business timezone at the edges.
    start_time_utc: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    end_time_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus), default=BookingStatus.CONFIRMED, nullable=False
    )
    cancel_token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=new_cancel_token, nullable=False
    )
    gcal_event_id: Mapped[str | None] = mapped_column(String(255))
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="bookings")


class CallbackRequest(Base):
    __tablename__ = "callback_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CallbackStatus] = mapped_column(
        Enum(CallbackStatus), default=CallbackStatus.PENDING, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="callbacks")

"""Outbound notifications: email via Gmail SMTP and SMS via Twilio.

Both channels are best-effort: if credentials are missing or sending fails,
the error is logged and the calling flow continues.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from twilio.rest import Client as TwilioClient

from app.core.config import Settings

logger = logging.getLogger(__name__)

_TIME_FORMAT = "%A, %d %B %Y at %I:%M %p"


def _format_local(dt_local: datetime) -> str:
    return dt_local.strftime(_TIME_FORMAT)


class EmailService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.gmail_address and self._settings.gmail_app_password)

    def _send(self, to_email: str, subject: str, html_body: str) -> bool:
        if not self.enabled:
            logger.warning("Email not configured (GMAIL_ADDRESS/GMAIL_APP_PASSWORD); skipping")
            return False
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{self._settings.business_name} <{self._settings.gmail_address}>"
        message["To"] = to_email
        message.attach(MIMEText(html_body, "html"))
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
                server.login(
                    self._settings.gmail_address, self._settings.gmail_app_password
                )
                server.sendmail(
                    self._settings.gmail_address, [to_email], message.as_string()
                )
            logger.info("Email sent to %s: %s", to_email, subject)
            return True
        except Exception as exc:
            logger.exception("Failed to send email to %s: %s", to_email, exc)
            return False

    def _wrap(self, title: str, body_html: str) -> str:
        return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;
            border:1px solid #e5e7eb;border-radius:12px;overflow:hidden">
  <div style="background:#111827;color:#ffffff;padding:20px 28px">
    <h2 style="margin:0;font-size:18px">{self._settings.business_name}</h2>
  </div>
  <div style="padding:28px">
    <h3 style="margin-top:0;color:#111827">{title}</h3>
    {body_html}
    <p style="color:#6b7280;font-size:12px;margin-top:28px">
      This is an automated message from {self._settings.business_name}.
    </p>
  </div>
</div>"""

    def send_booking_confirmation(
        self,
        *,
        to_email: str,
        customer_name: str,
        start_local: datetime,
        cancel_url: Optional[str],
    ) -> bool:
        when = _format_local(start_local)
        cancel_html = (
            f"""<p>If you need to cancel, use this link:<br>
            <a href="{cancel_url}" style="color:#2563eb">{cancel_url}</a></p>"""
            if cancel_url
            else ""
        )
        body = f"""\
<p>Hi {customer_name},</p>
<p>Your meeting is confirmed for:</p>
<p style="font-size:16px;font-weight:bold;color:#111827">{when}</p>
{cancel_html}
<p>We look forward to speaking with you!</p>"""
        return self._send(to_email, "Your meeting is confirmed", self._wrap("Booking confirmed", body))

    def send_booking_reminder(
        self, *, to_email: str, customer_name: str, start_local: datetime
    ) -> bool:
        when = _format_local(start_local)
        body = f"""\
<p>Hi {customer_name},</p>
<p>This is a friendly reminder that your meeting starts in about 1 hour:</p>
<p style="font-size:16px;font-weight:bold;color:#111827">{when}</p>
<p>See you soon!</p>"""
        return self._send(
            to_email, "Reminder: your meeting starts in 1 hour", self._wrap("Meeting reminder", body)
        )

    def send_booking_cancellation(
        self, *, to_email: str, customer_name: str, start_local: datetime
    ) -> bool:
        when = _format_local(start_local)
        body = f"""\
<p>Hi {customer_name},</p>
<p>Your meeting scheduled for <strong>{when}</strong> has been cancelled.</p>
<p>Feel free to call us anytime to book a new appointment.</p>"""
        return self._send(to_email, "Your meeting was cancelled", self._wrap("Booking cancelled", body))


class SmsService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.twilio_account_sid
            and self._settings.twilio_auth_token
            and self._settings.twilio_phone_number
        )

    def send(self, to_phone: str, body: str) -> bool:
        if not self.enabled:
            logger.warning("Twilio SMS not configured; skipping")
            return False
        try:
            client = TwilioClient(
                self._settings.twilio_account_sid, self._settings.twilio_auth_token
            )
            message = client.messages.create(
                to=to_phone, from_=self._settings.twilio_phone_number, body=body
            )
            logger.info("SMS sent to %s (SID: %s)", to_phone, message.sid)
            return True
        except Exception as exc:
            logger.exception("Failed to send SMS to %s: %s", to_phone, exc)
            return False

    def send_callback_promise(self, to_phone: str) -> bool:
        return self.send(
            to_phone,
            f"{self._settings.business_name}: Thanks for calling! We couldn't complete "
            "your request on the call, but we've saved your number and one of our team "
            "members will call you back shortly.",
        )

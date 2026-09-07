"""Sync bookings to the business Google Calendar via a service account.

The database is the source of truth; calendar sync is best-effort. If the
service account file or calendar id is not configured, sync is silently
skipped so the booking flow keeps working.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.core.config import Settings

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


class BusinessCalendar:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = None

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.business_calendar_id
            and os.path.exists(self._settings.google_service_account_file)
        )

    def _get_service(self):
        if self._service is None:
            credentials = service_account.Credentials.from_service_account_file(
                self._settings.google_service_account_file, scopes=_SCOPES
            )
            self._service = build(
                "calendar", "v3", credentials=credentials, cache_discovery=False
            )
        return self._service

    def create_event(
        self,
        *,
        summary: str,
        description: str,
        start_local: datetime,
        end_local: datetime,
    ) -> Optional[str]:
        """Create a calendar event and return its id, or None if sync is off/fails."""
        if not self.enabled:
            logger.info("Google Calendar sync not configured; skipping event creation")
            return None
        try:
            event = {
                "summary": summary,
                "description": description,
                "start": {
                    "dateTime": start_local.isoformat(),
                    "timeZone": self._settings.business_timezone,
                },
                "end": {
                    "dateTime": end_local.isoformat(),
                    "timeZone": self._settings.business_timezone,
                },
            }
            created = (
                self._get_service()
                .events()
                .insert(calendarId=self._settings.business_calendar_id, body=event)
                .execute()
            )
            event_id = created.get("id")
            logger.info("Created Google Calendar event %s", event_id)
            return event_id
        except Exception as exc:
            logger.exception("Google Calendar event creation failed: %s", exc)
            return None

    def delete_event(self, event_id: str) -> None:
        if not self.enabled or not event_id:
            return
        try:
            self._get_service().events().delete(
                calendarId=self._settings.business_calendar_id, eventId=event_id
            ).execute()
            logger.info("Deleted Google Calendar event %s", event_id)
        except Exception as exc:
            logger.exception("Google Calendar event deletion failed: %s", exc)

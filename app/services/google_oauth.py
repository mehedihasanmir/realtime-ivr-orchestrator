from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Optional

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def build_flow(client_secrets_path: str, redirect_uri: str) -> Flow:
    return Flow.from_client_secrets_file(
        client_secrets_path,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


class TokenStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load_raw(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

    def _save_raw(self, data: dict) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)

    def get_credentials(self, user_id: str) -> Optional[Credentials]:
        with self._lock:
            data = self._load_raw()
            raw = data.get(user_id)
            if not raw:
                return None
            return Credentials.from_authorized_user_info(raw, SCOPES)

    def set_credentials(self, user_id: str, credentials: Credentials) -> None:
        with self._lock:
            data = self._load_raw()
            data[user_id] = json.loads(credentials.to_json())
            self._save_raw(data)

    def refresh_credentials(self, user_id: str, credentials: Credentials) -> Credentials:
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(GoogleRequest())
            self.set_credentials(user_id, credentials)
        return credentials


class StateSigner:
    def __init__(self, secret: str, max_age_seconds: int = 600) -> None:
        self._secret = secret.encode("utf-8")
        self._max_age_seconds = max_age_seconds

    def sign(self, user_id: str) -> str:
        payload = {
            "uid": user_id,
            "ts": int(time.time()),
            "nonce": secrets.token_urlsafe(8),
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._secret, raw, hashlib.sha256).hexdigest()
        token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return f"{token}.{signature}"

    def verify(self, state: str) -> Optional[str]:
        try:
            token, signature = state.rsplit(".", 1)
            padded = token + "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
            expected = hmac.new(self._secret, raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(raw.decode("utf-8"))
            timestamp = int(payload.get("ts", 0))
            if time.time() - timestamp > self._max_age_seconds:
                return None
            return payload.get("uid")
        except Exception:
            return None


class CodeVerifierStore:
    def __init__(self, max_age_seconds: int = 600) -> None:
        self._max_age_seconds = max_age_seconds
        self._lock = threading.Lock()
        self._data: dict[str, tuple[str, int]] = {}

    def set(self, state: str, code_verifier: str) -> None:
        with self._lock:
            self._data[state] = (code_verifier, int(time.time()))

    def pop(self, state: str) -> Optional[str]:
        with self._lock:
            item = self._data.pop(state, None)
        if not item:
            return None
        code_verifier, timestamp = item
        if time.time() - timestamp > self._max_age_seconds:
            return None
        return code_verifier

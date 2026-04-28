import logging
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import get_settings
from app.services.google_oauth import CodeVerifierStore, StateSigner, TokenStore, build_flow

logger = logging.getLogger(__name__)
router = APIRouter()
_code_verifier_store = CodeVerifierStore()


def _normalize_e164(raw: str) -> str:
    cleaned = re.sub(r"[^0-9+]", "", raw)
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    if cleaned.startswith("+"):
        return cleaned
    return f"+{cleaned}" if cleaned else ""


@router.get("/auth/google/start")
async def google_start(request: Request, user_id: str) -> RedirectResponse:
    settings = get_settings()
    user_id = _normalize_e164(user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    signer = StateSigner(settings.google_oauth_state_secret)
    state = signer.sign(user_id)
    redirect_uri = str(request.url_for("google_callback"))
    flow = build_flow(settings.google_oauth_client_secrets_path, redirect_uri)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    if not flow.code_verifier:
        raise HTTPException(status_code=500, detail="Missing PKCE code verifier")
    _code_verifier_store.set(state, flow.code_verifier)
    return RedirectResponse(auth_url)


@router.get("/auth/google/callback", name="google_callback")
async def google_callback(request: Request, code: str, state: str) -> HTMLResponse:
    settings = get_settings()
    signer = StateSigner(settings.google_oauth_state_secret)
    user_id = signer.verify(state)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    code_verifier = _code_verifier_store.pop(state)
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Missing or expired code verifier")

    redirect_uri = str(request.url_for("google_callback"))
    flow = build_flow(settings.google_oauth_client_secrets_path, redirect_uri)
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials

    token_store = TokenStore(settings.google_oauth_token_path)
    token_store.set_credentials(user_id, creds)
    logger.info("Stored Google OAuth credentials for user_id=%s", user_id)

    return HTMLResponse("Google Calendar connected. You can close this window.")

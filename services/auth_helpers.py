"""OAuth state management, auth cookies, and Azure token helpers."""

import json
import logging
import time
from typing import Optional

from fastapi import Request

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory OAuth state cache (backup to session storage)
# ---------------------------------------------------------------------------

_oauth_state_cache: dict[str, float] = {}


def cleanup_oauth_cache():
    """Remove OAuth states older than the configured TTL."""
    current_time = time.time()
    expired = [s for s, ts in _oauth_state_cache.items() if current_time - ts > config.OAUTH_STATE_TTL]
    for s in expired:
        _oauth_state_cache.pop(s, None)


def store_oauth_state(state: str):
    cleanup_oauth_cache()
    _oauth_state_cache[state] = time.time()


def verify_oauth_state(state: str) -> bool:
    cleanup_oauth_cache()
    return state in _oauth_state_cache


def remove_oauth_state(state: str):
    _oauth_state_cache.pop(state, None)


# ---------------------------------------------------------------------------
# Auth cookie helper
# ---------------------------------------------------------------------------

def set_auth_cookie(response, session_token: str, *, secure: Optional[bool] = None):
    """Apply the auth session cookie to *response* with consistent parameters."""
    if secure is None:
        secure = config.COOKIE_SECURE
    response.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=secure,
        samesite=config.COOKIE_SAMESITE,
        max_age=config.SESSION_MAX_AGE,
    )


# ---------------------------------------------------------------------------
# Azure OAuth helpers
# ---------------------------------------------------------------------------

def verify_callback_state(request: Request, state: Optional[str]) -> bool:
    """Check the OAuth *state* against session storage and the in-memory cache."""
    if not state:
        return False
    stored_state = None
    try:
        _ = request.session
        stored_state = request.session.get("azure_oauth_state")
    except RuntimeError:
        logger.debug("Session middleware unavailable during state verification")
    if stored_state and state == stored_state:
        return True
    if verify_oauth_state(state):
        try:
            request.session["azure_oauth_state"] = state
        except RuntimeError:
            logger.debug("Session middleware unavailable; state stored in memory only")
        return True
    return False


async def exchange_auth_code(code: str, redirect_uri: str) -> Optional[dict]:
    """Exchange an authorisation code for tokens.  Returns the token dict or None."""
    from auth import AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TOKEN_ENDPOINT
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            AZURE_TOKEN_ENDPOINT,
            data={
                "client_id": AZURE_CLIENT_ID,
                "client_secret": AZURE_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            try:
                logger.error("Token exchange error: %s", resp.json())
            except (ValueError, json.JSONDecodeError):
                logger.error("Token exchange error: %s", resp.text[:500])
            return None
        return resp.json()


def extract_username_from_token(id_token: str) -> str:
    """Decode an Azure ID token and return the best username claim."""
    try:
        import jwt
        user_info = jwt.decode(id_token, options={"verify_signature": False})
        return (
            user_info.get("preferred_username")
            or user_info.get("email")
            or user_info.get("upn")
            or user_info.get("name")
            or "azure_user"
        )
    except (ImportError, ValueError, KeyError) as exc:
        logger.debug("JWT decode failed, falling back to manual decode: %s", exc)
    try:
        import base64 as b64
        parts = id_token.split('.')
        if len(parts) >= 2:
            payload = parts[1] + '=' * (4 - len(parts[1]) % 4)
            info = json.loads(b64.urlsafe_b64decode(payload))
            return info.get("preferred_username") or info.get("email") or "azure_user"
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Manual token decode failed: %s", exc)
    return "azure_user"


def resolve_redirect_uri(request: Request) -> str:
    """Build the OAuth redirect URI, accounting for ngrok tunnels."""
    from auth import AZURE_REDIRECT_URI
    host = request.headers.get("host", "")
    if host and "ngrok" in host.lower():
        return f"https://{host}/auth/callback"
    return AZURE_REDIRECT_URI

"""Authentication routes: login, logout, Azure SSO, admin login, and home page."""

import logging
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse

import config

logger = logging.getLogger(__name__)
from auth import (
    verify_user, create_session_token, verify_session_token,
    AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_REDIRECT_URI,
    AZURE_AUTHORIZATION_ENDPOINT, AZURE_API_SCOPE,
)
from dependencies import templates, require_auth
from services.auth_helpers import (
    store_oauth_state, remove_oauth_state,
    set_auth_cookie, verify_callback_state,
    exchange_auth_code, extract_username_from_token,
    resolve_redirect_uri,
)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, current_user: str = Depends(require_auth)):
    """Home page with navigation to both stages."""
    return templates.TemplateResponse("home.html", {"request": request, "username": current_user})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page — accessible without authentication."""
    session_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if session_token:
        username = verify_session_token(session_token)
        if username:
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    error = request.query_params.get("error")
    response = templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "use_azure_sso": config.USE_AZURE_SSO,
    })
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Admin login page — for troubleshooting purposes."""
    session_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if session_token:
        username = verify_session_token(session_token)
        if username:
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    error = request.query_params.get("error")
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": error})


@router.post("/admin/login")
async def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle admin login form submission."""
    if verify_user(username, password):
        session_token = create_session_token(username)
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        set_auth_cookie(response, session_token)
        return response
    return RedirectResponse(url="/admin/login?error=invalid_credentials", status_code=status.HTTP_302_FOUND)


@router.get("/login/azure")
async def login_azure(request: Request):
    """Initiate Azure AD SSO login."""
    import secrets

    if not AZURE_CLIENT_ID or not AZURE_TENANT_ID:
        return RedirectResponse(url="/login?error=azure_not_configured", status_code=status.HTTP_302_FOUND)

    state = secrets.token_urlsafe(32)

    try:
        _ = request.session
        request.session["azure_oauth_state"] = state
    except RuntimeError:
        logger.debug("Session middleware unavailable during Azure login")

    store_oauth_state(state)

    host = request.headers.get("host", "")
    if host and "ngrok" in host.lower():
        redirect_uri = f"https://{host}/auth/callback"
    else:
        redirect_uri = AZURE_REDIRECT_URI

    scope = f"openid profile email {AZURE_API_SCOPE}"
    params = {
        "client_id": AZURE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": scope,
        "state": state,
        "prompt": "select_account",
    }

    auth_url = f"{AZURE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/auth/callback")
async def azure_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Handle Azure AD OAuth callback."""
    if error:
        return RedirectResponse(url=f"/login?error=azure_{error}", status_code=status.HTTP_302_FOUND)
    if not code:
        return RedirectResponse(url="/login?error=no_code", status_code=status.HTTP_302_FOUND)
    if not verify_callback_state(request, state):
        return RedirectResponse(url="/login?error=invalid_state", status_code=status.HTTP_302_FOUND)

    redirect_uri = resolve_redirect_uri(request)

    try:
        token_data = await exchange_auth_code(code, redirect_uri)
        if token_data is None:
            return RedirectResponse(url="/login?error=token_exchange_failed", status_code=status.HTTP_302_FOUND)

        access_token = token_data.get("access_token")
        id_token = token_data.get("id_token")
        if not access_token:
            return RedirectResponse(url="/login?error=no_access_token", status_code=status.HTTP_302_FOUND)
        if not id_token:
            return RedirectResponse(url="/login?error=no_id_token", status_code=status.HTTP_302_FOUND)

        username = extract_username_from_token(id_token)
        session_token = create_session_token(username)

        try:
            request.session.pop("azure_oauth_state", None)
        except RuntimeError:
            logger.debug("Session middleware unavailable during callback cleanup")
        remove_oauth_state(state)

        use_https = request.url.scheme == "https" or config.IS_PRODUCTION
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        set_auth_cookie(response, session_token, secure=use_https)
        return response

    except Exception as e:
        logger.exception("Azure auth error: %s", e)
        error_message = "auth_failed"
        err_str = str(e).lower()
        if "client_secret" in err_str or "invalid_client" in err_str:
            error_message = "invalid_client_config"
        elif "token" in err_str:
            error_message = "token_error"
        return RedirectResponse(url=f"/login?error={error_message}", status_code=status.HTTP_302_FOUND)


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle login form submission."""
    if verify_user(username, password):
        session_token = create_session_token(username)
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        set_auth_cookie(response, session_token)
        return response
    return RedirectResponse(url="/login?error=invalid_credentials", status_code=status.HTTP_302_FOUND)


@router.get("/logout")
async def logout():
    """Handle logout."""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(config.SESSION_COOKIE_NAME)
    return response

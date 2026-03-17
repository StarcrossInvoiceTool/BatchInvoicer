"""Shared FastAPI dependencies: templates, auth guards."""

from typing import Optional

from fastapi import Depends, Request, HTTPException, status
from fastapi.templating import Jinja2Templates

import config
from auth import verify_session_token, azure_scheme


templates = Jinja2Templates(directory=config.TEMPLATES_DIR, auto_reload=not config.IS_PRODUCTION)


async def get_azure_user(request: Request, token: Optional[str] = Depends(azure_scheme)) -> Optional[dict]:
    """Get current authenticated user from Azure AD token."""
    if token:
        return token
    return None


async def get_current_user(request: Request) -> Optional[str]:
    """Get current authenticated user from session cookie."""
    session_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not session_token:
        return None
    return verify_session_token(session_token)


async def require_auth(request: Request, current_user: Optional[str] = Depends(get_current_user)):
    """Dependency that requires authentication — raises 401 if not authenticated."""
    if not current_user:
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail="Authentication required")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return current_user

"""Stage 3 route: invoice editing page."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

from dependencies import templates, require_auth

router = APIRouter()


@router.get("/stage3", response_class=HTMLResponse)
async def stage3_page(request: Request, current_user: str = Depends(require_auth)):
    """Invoice Editing: Edit saved HTML invoice page."""
    return templates.TemplateResponse("stage3.html", {"request": request})

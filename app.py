"""Batch Invoicer — application entry point.

Creates the FastAPI app, registers middleware, mounts static files,
includes all route modules, and provides the exception handler.
"""

import logging
import os

from fastapi import FastAPI, Request, HTTPException, status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import config
from routes import auth, stage1, stage2, stage3, invoice, summary

# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(title="Batch Invoicer", description="Convert XLSX to CSV and generate invoices")

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    same_site=config.COOKIE_SAMESITE,
    https_only=config.SESSION_HTTPS_ONLY,
)

# ---------------------------------------------------------------------------
# Ensure required directories exist
# ---------------------------------------------------------------------------

for _dir in (config.UPLOADS_DIR, config.INVOICE_HTML_DIR, config.TEMP_DIR, config.STATIC_DIR):
    os.makedirs(_dir, exist_ok=True)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

if os.path.exists(config.STATIC_DIR):
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(stage1.router)
app.include_router(stage2.router)
app.include_router(stage3.router)
app.include_router(invoice.router)
app.include_router(summary.router)

# ---------------------------------------------------------------------------
# Global handlers
# ---------------------------------------------------------------------------


@app.get("/favicon.ico")
async def favicon():
    """Handle favicon requests."""
    return Response(status_code=204)


@app.exception_handler(HTTPException)
async def auth_exception_handler(request: Request, exc: HTTPException):
    """Handle authentication redirects for HTML routes."""
    if exc.status_code == status.HTTP_401_UNAUTHORIZED and not request.url.path.startswith("/api/"):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if exc.status_code == status.HTTP_401_UNAUTHORIZED and request.url.path.startswith("/api/"):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# ---------------------------------------------------------------------------
# Dev server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)

"""
Centralised configuration for the Batch Invoicer application.

All tuneable values live here so they can be changed in one place or
overridden via environment variables / a .env file.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR: Path = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Security / sessions
# ---------------------------------------------------------------------------
SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-only-change-in-production")
SESSION_COOKIE_NAME: str = "session_token"
SESSION_MAX_AGE: int = int(os.environ.get("SESSION_MAX_AGE", "86400"))  # 24 h
OAUTH_STATE_TTL: int = int(os.environ.get("OAUTH_STATE_TTL", "600"))    # 10 min

# ---------------------------------------------------------------------------
# Environment / deployment
# ---------------------------------------------------------------------------
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION: bool = ENVIRONMENT.lower() == "production"
USE_AZURE_SSO: bool = os.getenv("USE_AZURE_SSO", "false").lower() == "true"
COOKIE_SECURE: bool = IS_PRODUCTION
COOKIE_SAMESITE: str = "lax"
SESSION_HTTPS_ONLY: bool = IS_PRODUCTION
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))

# ---------------------------------------------------------------------------
# Directory paths
# ---------------------------------------------------------------------------
TEMP_DIR: str = os.getenv("TEMP_DIR", "temp")
UPLOADS_DIR: str = os.getenv("UPLOADS_DIR", "uploads")
INVOICE_HTML_DIR: str = os.getenv("INVOICE_HTML_DIR", "invoice html")
STATIC_DIR: str = os.getenv("STATIC_DIR", "static")
TEMPLATES_DIR: str = os.getenv("TEMPLATES_DIR", "templates")

# ---------------------------------------------------------------------------
# Invoice templates
# ---------------------------------------------------------------------------
INVOICE_TEMPLATE_STYLE1: str = "Invoice 2.html"
INVOICE_TEMPLATE_STYLE2: str = "Invoice 2 - Style 2.html"
DEFAULT_INVOICE_STYLE: str = "style1"

# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------
LOGO_FILENAME: str = "bears-pts logo.jpg"
PAID_STAMP_FILENAME: str = "PAID STAMP.png"

# ---------------------------------------------------------------------------
# Business defaults — bank details, VAT, etc.
# ---------------------------------------------------------------------------
DEFAULT_BANK_NAME: str = os.getenv("BANK_NAME", "Lloyds Bank Plc")
DEFAULT_ACCOUNT_NAME: str = os.getenv("ACCOUNT_NAME", "Starcross Trading Limited")
DEFAULT_ACCOUNT_NUMBER: str = os.getenv("ACCOUNT_NUMBER", "82082760")
DEFAULT_SORT_CODE: str = os.getenv("SORT_CODE", "30-99-21")
DEFAULT_VAT_PERCENTAGE: str = os.getenv("DEFAULT_VAT_PERCENTAGE", "20")

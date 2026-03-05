"""
Authentication module for the Batch Invoicer application.

Handles both local whitelist authentication and Azure AD SSO.
All sensitive values are loaded from environment variables.
See ENV_VARS.md for the full list of required variables.
"""
import json
import os
from pathlib import Path
from typing import Optional

from itsdangerous import URLSafeTimedSerializer
from passlib.context import CryptContext
from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-in-production")
SESSION_COOKIE_NAME = "session_token"

# ---------------------------------------------------------------------------
# Local (whitelist) authentication
# ---------------------------------------------------------------------------
WHITELIST_FILE = Path(__file__).parent / "whitelist.json"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
serializer = URLSafeTimedSerializer(SECRET_KEY)


def load_whitelist() -> dict:
    """Load the whitelist from JSON file"""
    if not WHITELIST_FILE.exists():
        default_whitelist = {
            "users": [
                {
                    "username": "admin",
                    "password": "admin123"
                }
            ]
        }
        with open(WHITELIST_FILE, 'w') as f:
            json.dump(default_whitelist, f, indent=2)
        return default_whitelist

    with open(WHITELIST_FILE, 'r') as f:
        return json.load(f)


def verify_user(username: str, password: str) -> bool:
    """Verify if username and password match whitelist"""
    whitelist = load_whitelist()

    for user in whitelist.get("users", []):
        if user.get("username") == username:
            stored_password = user.get("password") or user.get("password_hash")

            if stored_password.startswith("$2b$") or stored_password.startswith("$2a$"):
                return pwd_context.verify(password, stored_password)
            else:
                return password == stored_password

    return False


def create_session_token(username: str) -> str:
    """Create a signed session token"""
    return serializer.dumps(username)


def verify_session_token(token: str, max_age: int = 86400) -> Optional[str]:
    """Verify and extract username from session token (default 24 hours)"""
    try:
        username = serializer.loads(token, max_age=max_age)
        return username
    except Exception:
        return None


def hash_password(password: str) -> str:
    """Hash a password for storage"""
    return pwd_context.hash(password)


def add_user_to_whitelist(username: str, password: str, hash_password_flag: bool = True):
    """Add a new user to the whitelist"""
    whitelist = load_whitelist()

    for user in whitelist.get("users", []):
        if user.get("username") == username:
            raise ValueError(f"User {username} already exists")

    new_user = {"username": username}

    if hash_password_flag:
        new_user["password_hash"] = hash_password(password)
    else:
        new_user["password"] = password

    whitelist.setdefault("users", []).append(new_user)

    with open(WHITELIST_FILE, 'w') as f:
        json.dump(whitelist, f, indent=2)

# ---------------------------------------------------------------------------
# Azure AD SSO
# ---------------------------------------------------------------------------
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "")
REQUIRED_MAILBOX = os.getenv("REQUIRED_MAILBOX", "")

AZURE_API_SCOPE = f"api://{AZURE_CLIENT_ID}/userImpersonations" if AZURE_CLIENT_ID else ""

azure_scheme = SingleTenantAzureAuthorizationCodeBearer(
    app_client_id=AZURE_CLIENT_ID or "not-configured",
    tenant_id=AZURE_TENANT_ID or "not-configured",
    scopes={AZURE_API_SCOPE: 'access as user'} if AZURE_API_SCOPE else {},
    allow_guest_users=True,
) if AZURE_CLIENT_ID and AZURE_TENANT_ID else None

AZURE_AUTHORIZATION_ENDPOINT = (
    f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/authorize"
    if AZURE_TENANT_ID else ""
)
AZURE_TOKEN_ENDPOINT = (
    f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token"
    if AZURE_TENANT_ID else ""
)

GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"

"""
Authentication utilities for the Batch Invoicer application
"""
import json
import os
from pathlib import Path
from typing import Optional
from itsdangerous import URLSafeTimedSerializer
from passlib.context import CryptContext

# Secret key for session signing (in production, use environment variable)
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
SESSION_COOKIE_NAME = "session_token"
WHITELIST_FILE = Path(__file__).parent / "whitelist.json"

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Session serializer
serializer = URLSafeTimedSerializer(SECRET_KEY)


def load_whitelist() -> dict:
    """Load the whitelist from JSON file"""
    if not WHITELIST_FILE.exists():
        # Create default whitelist if it doesn't exist
        default_whitelist = {
            "users": [
                {
                    "username": "admin",
                    "password": "admin123"  # Change this default password
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
            # Check if password is hashed or plain text
            stored_password = user.get("password") or user.get("password_hash")
            
            if stored_password.startswith("$2b$") or stored_password.startswith("$2a$"):
                # Password is hashed
                return pwd_context.verify(password, stored_password)
            else:
                # Password is plain text (for simple setup)
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
    
    # Check if user already exists
    for user in whitelist.get("users", []):
        if user.get("username") == username:
            raise ValueError(f"User {username} already exists")
    
    # Add new user
    new_user = {
        "username": username
    }
    
    if hash_password_flag:
        new_user["password_hash"] = hash_password(password)
    else:
        new_user["password"] = password
    
    whitelist.setdefault("users", []).append(new_user)
    
    with open(WHITELIST_FILE, 'w') as f:
        json.dump(whitelist, f, indent=2)


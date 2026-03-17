"""
Centralised helpers for locating and creating temp-directory-based sessions.

Every batch/conversion/invoice operation stores artefacts under ``config.TEMP_DIR``
in directories named with a prefix that encodes the session type and ID, e.g.

    temp/convert_<hex>_<suffix>/
    temp/batch_<hex>_<suffix>/
    temp/html_<hex>_<suffix>/

The lookup helpers here replace the ``os.walk`` + string-match pattern that was
previously duplicated 12+ times across route handlers.
"""

import os
import pickle
import tempfile
from pathlib import Path
from typing import Optional

import config


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------

def create_session_dir(prefix: str) -> tuple[str, str]:
    """Create a new session directory and return ``(session_id, dir_path)``."""
    session_id = os.urandom(16).hex()
    dir_path = tempfile.mkdtemp(dir=config.TEMP_DIR, prefix=f"{prefix}{session_id}_")
    return session_id, dir_path


# ---------------------------------------------------------------------------
# Directory lookups
# ---------------------------------------------------------------------------

def find_conversion_dir(session_id: str) -> Optional[str]:
    """Return the path of the ``convert_<session_id>*`` directory, or *None*."""
    needle = f"convert_{session_id}"
    for root, dirs, _files in os.walk(config.TEMP_DIR):
        for d in dirs:
            if needle in d:
                return os.path.join(root, d)
    return None


def find_batch_dir(batch_session_id: str) -> Optional[str]:
    """Return the path of the ``batch_<id>*`` directory, or *None*."""
    needle = f"batch_{batch_session_id}"
    for root, _dirs, _files in os.walk(config.TEMP_DIR):
        if needle in root:
            return root
    return None


# ---------------------------------------------------------------------------
# Invoice-data (pickle) lookups
# ---------------------------------------------------------------------------

def find_invoice_data_path(session_id: str) -> Optional[str]:
    """Return the full path to ``<session_id>_invoice_data.pkl``, or *None*."""
    target = f"{session_id}_invoice_data.pkl"
    for root, _dirs, files in os.walk(config.TEMP_DIR):
        if target in files:
            return os.path.join(root, target)
    return None


def find_invoice_data_with_dir(session_id: str) -> tuple[Optional[str], Optional[str]]:
    """Return ``(invoice_data_path, containing_dir)`` or ``(None, None)``."""
    target = f"{session_id}_invoice_data.pkl"
    for root, _dirs, files in os.walk(config.TEMP_DIR):
        if target in files:
            return os.path.join(root, target), root
    return None, None


def find_batch_invoice_files(batch_session_id: str) -> tuple[Optional[str], list[str]]:
    """Return ``(batch_dir, [pkl_paths...])`` for every invoice pkl in the batch."""
    needle = f"batch_{batch_session_id}"
    for root, _dirs, files in os.walk(config.TEMP_DIR):
        if needle in root:
            pkls = [
                os.path.join(root, f)
                for f in files
                if f.endswith("_invoice_data.pkl")
            ]
            return root, pkls
    return None, []


# ---------------------------------------------------------------------------
# Pickle convenience wrappers
# ---------------------------------------------------------------------------

def load_invoice_data(session_id: str) -> dict:
    """Load and return the invoice-data dict for *session_id*."""
    path = find_invoice_data_path(session_id)
    if path is None:
        raise FileNotFoundError(f"No invoice data found for session {session_id}")
    with open(path, "rb") as f:
        return pickle.load(f)


def save_invoice_data(path: str, data: dict) -> None:
    """Persist *data* to the given pickle *path*."""
    with open(path, "wb") as f:
        pickle.dump(data, f)

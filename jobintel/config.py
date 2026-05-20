from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

# Load .env from project root (parent of package)
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    v = _env(key)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = _env(key).lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


# --- Email ---
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
MAIL_FROM = _env("MAIL_FROM") or SMTP_USER
MAIL_TO = _env("MAIL_TO") or MAIL_FROM

# --- Adzuna (UK gb, US us, Canada ca) ---
ADZUNA_APP_ID = _env("ADZUNA_APP_ID")
ADZUNA_APP_KEY = _env("ADZUNA_APP_KEY")
ADZUNA_ENABLED = _env_bool("ADZUNA_ENABLED", True) and bool(ADZUNA_APP_ID and ADZUNA_APP_KEY)

# --- New sources (all free, no auth required) ---
THEMUSE_ENABLED = _env_bool("THEMUSE_ENABLED", True)
REMOTEOK_ENABLED = _env_bool("REMOTEOK_ENABLED", True)
JOBICY_COUNT = _env_int("JOBICY_COUNT", 50)

# HTTP
HTTP_TIMEOUT = 45.0
USER_AGENT = (
    "JobIntel/0.1 (+https://github.com/local/jobintel; personal job digest; contact: same as operator)"
)

# Logging
LOG_LEVEL = _env("LOG_LEVEL", "INFO")


def validate(*, email_required: bool = True) -> None:
    """Log warnings for missing credentials. Call at startup."""
    if email_required and (not SMTP_USER or not SMTP_PASSWORD):
        log.warning(
            "SMTP_USER / SMTP_PASSWORD not set — email will fail. "
            "Use --no-email to suppress this warning."
        )
    if not MAIL_TO:
        log.warning("MAIL_TO not set — digest has no recipient.")
    if _env_bool("ADZUNA_ENABLED", True) and not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        log.warning(
            "ADZUNA_ENABLED=true but ADZUNA_APP_ID/KEY missing — Adzuna source disabled. "
            "Get a free key at https://developer.adzuna.com/"
        )

"""Security helpers: localhost enforcement, origin validation, redaction, clamping."""

import hashlib
import os
import secrets
import sys
from pathlib import Path

LOCALHOST_ADDRS = {"127.0.0.1", "::1", "localhost"}


def is_localhost(host: str) -> bool:
    return host.split(":")[0] in LOCALHOST_ADDRS


def validate_origin(origin: str | None, host: str) -> bool:
    """Allow requests with no origin (direct tool access) or matching localhost origin."""
    if origin is None:
        return True
    try:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        return parsed.hostname in LOCALHOST_ADDRS
    except Exception:
        return False


def clamp(text: str | None, n: int = 200) -> str | None:
    if not isinstance(text, str):
        return text
    return text[:n] + "…" if len(text) > n else text


_SECRET_PATTERNS = [
    "password", "secret", "token", "apikey", "api_key",
    "auth", "credential", "private_key", "access_key",
]


def redact(value: str | None) -> str | None:
    """Redact values whose key looks like a secret. Apply to user-supplied strings only."""
    if value is None:
        return None
    for pattern in _SECRET_PATTERNS:
        if pattern in value.lower():
            return "[REDACTED]"
    return value


def generate_action_token() -> str:
    return secrets.token_hex(32)


def validate_action_token(provided: str, expected: str) -> bool:
    return secrets.compare_digest(provided, expected)

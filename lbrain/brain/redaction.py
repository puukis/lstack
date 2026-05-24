"""Redaction helpers for LBrain storage and exports."""

import re

REDACTED = "<redacted>"

_PEM_RE = re.compile(
    r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|SSH PRIVATE KEY)[A-Z ]*-----.*?"
    r"-----END [A-Z ]*(?:PRIVATE KEY|SSH PRIVATE KEY)[A-Z ]*-----",
    re.DOTALL,
)
_AUTH_RE = re.compile(r"(?i)(Authorization\s*:\s*)Bearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_GITHUB_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{10,}\b")
_NPM_RE = re.compile(r"\bnpm_[A-Za-z0-9_=-]{8,}\b")
_OPENAI_RE = re.compile(r"\bsk-(?:test-)?[A-Za-z0-9][A-Za-z0-9_-]{6,}\b")
_SECRET_ASSIGN_RE = re.compile(
    r"(?im)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASS|API_KEY|AUTH|PRIVATE_KEY|NPM_TOKEN|GITHUB_TOKEN)"
    r"[A-Z0-9_]*\s*=\s*)([^\s\"']+|\"[^\"]*\"|'[^']*')"
)
_PASSWORD_RE = re.compile(r"(?i)\b(password\s*[:=]\s*)([^\s\"']+|\"[^\"]*\"|'[^']*')")


def redact_text(value, max_length=2000):
    """Return redacted text and redaction status."""
    if value is None:
        return None, "clean"
    text = str(value)
    if len(text) > max_length:
        text = text[:max_length] + "\n<truncated>"

    redacted = text
    redacted = _PEM_RE.sub(REDACTED, redacted)
    redacted = _AUTH_RE.sub(r"\1" + REDACTED, redacted)
    redacted = _JWT_RE.sub(REDACTED, redacted)
    redacted = _GITHUB_RE.sub(REDACTED, redacted)
    redacted = _NPM_RE.sub(REDACTED, redacted)
    redacted = _OPENAI_RE.sub(REDACTED, redacted)
    redacted = _SECRET_ASSIGN_RE.sub(r"\1" + REDACTED, redacted)
    redacted = _PASSWORD_RE.sub(r"\1" + REDACTED, redacted)

    if redacted != text:
        return redacted, "redacted"
    return redacted, "clean"


def combine_status(*statuses):
    if "blocked" in statuses:
        return "blocked"
    if "suspect" in statuses:
        return "suspect"
    if "redacted" in statuses:
        return "redacted"
    return "clean"


def redact_json(value, max_string_length=1000):
    """Redact strings inside JSON-compatible data."""
    if isinstance(value, dict):
        result = {}
        statuses = []
        for key, item in value.items():
            redacted_key, key_status = redact_text(str(key), max_length=max_string_length)
            redacted_item, item_status = redact_json(item, max_string_length=max_string_length)
            result[redacted_key] = redacted_item
            statuses.extend([key_status, item_status])
        return result, combine_status(*statuses)
    if isinstance(value, list):
        items = []
        statuses = []
        for item in value:
            redacted_item, status = redact_json(item, max_string_length=max_string_length)
            items.append(redacted_item)
            statuses.append(status)
        return items, combine_status(*statuses)
    if isinstance(value, str):
        return redact_text(value, max_length=max_string_length)
    return value, "clean"

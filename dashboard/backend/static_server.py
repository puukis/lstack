"""Safely serve frontend/dist/ static files."""

import mimetypes
import os
from pathlib import Path

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

_MIME_FALLBACK = "application/octet-stream"

_SAFE_EXTENSIONS = {
    ".html", ".css", ".js", ".jsx", ".ts", ".tsx",
    ".json", ".svg", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map",
    ".txt", ".webmanifest",
}


def _safe_path(requested: str) -> Path | None:
    """Resolve and validate that the path is inside FRONTEND_DIST."""
    if not FRONTEND_DIST.exists():
        return None
    rel = requested.lstrip("/")
    if not rel:
        rel = "index.html"
    candidate = (FRONTEND_DIST / rel).resolve()
    try:
        candidate.relative_to(FRONTEND_DIST.resolve())
    except ValueError:
        return None
    if candidate.suffix and candidate.suffix.lower() not in _SAFE_EXTENSIONS:
        return None
    return candidate if candidate.is_file() else None


def serve_static(path: str) -> tuple[int, str, bytes] | None:
    """Return (status, content_type, body) or None if not found.

    Callers should send the tuple as an HTTP response.
    SPA fallback: serve index.html for unknown paths so React Router works.
    """
    resolved = _safe_path(path)

    if resolved is None:
        # SPA fallback — send index.html so client-side routing works
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            mime = "text/html; charset=utf-8"
            return 200, mime, index.read_bytes()
        return None

    mime = mimetypes.guess_type(str(resolved))[0] or _MIME_FALLBACK
    if resolved.suffix == ".js":
        mime = "application/javascript"
    elif resolved.suffix == ".css":
        mime = "text/css"
    elif resolved.suffix == ".html":
        mime = "text/html; charset=utf-8"

    return 200, mime, resolved.read_bytes()


def dist_exists() -> bool:
    return (FRONTEND_DIST / "index.html").exists()

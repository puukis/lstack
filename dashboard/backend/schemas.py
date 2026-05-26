"""Shared response shapes and constants for the LStack Dashboard backend."""

SCHEMA_VERSION = 1
DASHBOARD_VERSION = "1.0.0"

API_ROUTES = [
    "GET /api/overview",
    "GET /api/lbrain",
    "GET /api/memory",
    "GET /api/health",
    "GET /api/actions",
    "GET /api/actions/audit",
]

FORBIDDEN_ROUTES = [
    "POST /api/run",
    "POST /api/command",
    "POST /api/git",
    "POST /api/receipt/finalize",
    "POST /api/passport/refresh",
    "POST /api/doctor/fix",
]

ALLOWED_READ_GIT_COMMANDS = [
    "rev-parse --abbrev-ref HEAD",
    "rev-parse --show-toplevel",
    "status --short",
    "log -1",
]

READ_ONLY_MODE = True

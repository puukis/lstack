"""Action registry — allowlisted V2 action definitions. V1: all disabled."""

from .schemas import SCHEMA_VERSION

_ACTION_REGISTRY = [
    {
        "id": "doctor.fix",
        "label": "Run doctor --fix",
        "category": "repair",
        "description": "Run lstack doctor --fix to repair installation issues.",
        "danger": "medium",
        "requires_confirmation": True,
        "requires_receipt": True,
        "requires_firewall_check": True,
        "requires_audit_log": True,
        "v1_behavior": "disabled",
        "enabled": False,
    },
    {
        "id": "passport.refresh",
        "label": "Refresh Repo Passport",
        "category": "lbrain",
        "description": "Run lstack brain passport refresh to update repo facts.",
        "danger": "low",
        "requires_confirmation": True,
        "requires_receipt": False,
        "requires_firewall_check": False,
        "requires_audit_log": True,
        "v1_behavior": "disabled",
        "enabled": False,
    },
    {
        "id": "health.run_fast",
        "label": "Run fast health check",
        "category": "quality",
        "description": "Run lstack health --fast --no-save to check project quality.",
        "danger": "low",
        "requires_confirmation": True,
        "requires_receipt": False,
        "requires_firewall_check": False,
        "requires_audit_log": True,
        "v1_behavior": "disabled",
        "enabled": False,
    },
    {
        "id": "memory.analytics",
        "label": "Show memory analytics",
        "category": "memory",
        "description": "Run lstack analytics to show observation and learning stats.",
        "danger": "low",
        "requires_confirmation": False,
        "requires_receipt": False,
        "requires_firewall_check": False,
        "requires_audit_log": True,
        "v1_behavior": "disabled",
        "enabled": False,
    },
]

V2_SAFETY_RULES = [
    "every action must be allowlisted",
    "every action must have a danger level",
    "every mutating action must require confirmation",
    "every coding action must open or attach to a Change Receipt",
    "risky commands must pass AI Mistake Firewall",
    "actions must be logged to the audit log",
    "no raw command runner",
    "no arbitrary shell input from browser",
    "no browser-initiated git mutations (push/pull/reset/clean)",
    "localhost-only remains default",
    "LAN access remains opt-in via --allow-lan",
    "user must inspect what will run before it runs",
]


def build_action_registry() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "interactive_ready": True,
        "enabled": False,
        "mode": "read_only_v1",
        "items": _ACTION_REGISTRY,
        "v2_rules": V2_SAFETY_RULES,
    }


def execute_action(action_id: str, params: dict, confirmed: bool = False) -> dict:
    """V2 stub — no actions are executable in V1."""
    item = next((a for a in _ACTION_REGISTRY if a["id"] == action_id), None)
    if item is None:
        return {"ok": False, "error": f"unknown action: {action_id}"}
    if not item["enabled"]:
        return {"ok": False, "error": "action disabled in V1", "v1_behavior": "disabled"}
    return {"ok": False, "error": "not implemented"}

"""
core/kill_switch.py — Safe-fail kill switch.

Design contract:
  - Missing file   → BLOCKED (safe fail, never crashes)
  - Malformed JSON → BLOCKED (safe fail)
  - Healthy state  → check the `active` field

Legacy lesson: the old system used a `triggered` field. We use `active: bool`.
A one-shot compatibility shim handles files that still use `triggered`.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_KILL_SWITCH_PATH = Path("shared/state/kill_switch.json")


class KillSwitchState(str, Enum):
    HEALTHY = "healthy"
    BLOCKED = "blocked"


def is_blocked(path: Path = _DEFAULT_KILL_SWITCH_PATH) -> bool:
    """
    Returns True if trading should be halted.

    Safe-fail: any read/parse error → True (blocked).
    Logs the reason so the operator knows what happened.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("kill_switch.json not found at %s — defaulting to BLOCKED", path)
        return True
    except OSError as exc:
        logger.error("Cannot read kill_switch.json: %s — defaulting to BLOCKED", exc)
        return True

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("kill_switch.json is malformed: %s — defaulting to BLOCKED", exc)
        return True

    # Primary field
    if "active" in data:
        result: bool = bool(data["active"])
        if result:
            reason = data.get("reason", "no reason given")
            logger.warning("Kill switch ACTIVE — %s", reason)
        return result

    # Legacy compatibility: old files used `triggered`
    if "triggered" in data:
        logger.warning(
            "kill_switch.json uses deprecated 'triggered' field — update to 'active'"
        )
        return bool(data["triggered"])

    # Unknown schema
    logger.error(
        "kill_switch.json has neither 'active' nor 'triggered' field — defaulting to BLOCKED"
    )
    return True


def set_blocked(reason: str, path: Path = _DEFAULT_KILL_SWITCH_PATH) -> None:
    """Write a kill switch file. Idempotent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"active": True, "reason": reason}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.critical("Kill switch ACTIVATED: %s", reason)


def set_healthy(path: Path = _DEFAULT_KILL_SWITCH_PATH) -> None:
    """Clear the kill switch. Creates the file if missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"active": False, "reason": None}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Kill switch cleared — system is HEALTHY")


def require_healthy(path: Path = _DEFAULT_KILL_SWITCH_PATH) -> None:
    """Raise if the kill switch is active. Use at entry points that must not trade."""
    if is_blocked(path):
        raise RuntimeError("Kill switch is active — trading halted")

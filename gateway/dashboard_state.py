"""
gateway/dashboard_state.py — Central state reader for AnalystTeam Dashboard v2.

Reads from shared JSON / JSONL state files and assembles the full dashboard payload.
All functions are safe-fail: they return empty structures on missing/malformed files.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State file paths
# ---------------------------------------------------------------------------
OPEN_POSITIONS_FILE = Path("shared/state/open_positions.json")
TRADE_JOURNAL_FILE  = Path("shared/state/trade_journal.jsonl")
KILL_SWITCH_FILE    = Path("shared/state/kill_switch.json")
GREEKS_FILE         = Path("shared/state/position_greeks.json")
PAUSED_FILE         = Path("shared/state/paused_analysts.json")
ACCOUNTS_FILE       = Path("configs/accounts.json")

# ---------------------------------------------------------------------------
# Known analysts
# ---------------------------------------------------------------------------
ANALYST_DISPLAY_NAMES: dict[str, str] = {
    "vinod_spx":     "Vinod SPX",
    "vinod_other":   "Vinod Other",
    "albert":        "Albert",
    "zabes":         "Zabes Swings",
    "adi":           "ADI Premium",
    "pilla_swings":  "Pilla Swings",
    "everest":       "Everest",
    "mag7":          "Mag7",
    "spy_spx_uw":    "SPY/SPX UW",
    "screener":      "Screener",
    "social_trends": "Social Trends",
    "technical_ta":  "Technical TA",
}

_SIGNAL_EVENTS = {"SIGNAL_APPROVED", "SIGNAL_REJECTED", "DUPLICATE_SIGNAL_DROPPED"}


# ---------------------------------------------------------------------------
# Individual readers
# ---------------------------------------------------------------------------

def read_positions() -> list[dict]:
    """Read OPEN_POSITIONS_FILE. Returns [] on any error."""
    try:
        raw = OPEN_POSITIONS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        # Some implementations wrap in {"positions": [...]}
        if isinstance(data, dict):
            return data.get("positions", [])
        return []
    except Exception as exc:
        logger.debug("read_positions: %s", exc)
        return []


def read_greeks() -> dict[str, dict]:
    """Read GREEKS_FILE. Returns dict keyed by position_id."""
    try:
        raw = GREEKS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        # If it's a list of greeks objects, key by position_id
        if isinstance(data, list):
            return {item["position_id"]: item for item in data if "position_id" in item}
        return {}
    except Exception as exc:
        logger.debug("read_greeks: %s", exc)
        return {}


def _iter_journal_lines() -> list[dict]:
    """Read all lines from TRADE_JOURNAL_FILE. Returns [] on error."""
    try:
        lines = TRADE_JOURNAL_FILE.read_text(encoding="utf-8").splitlines()
        result = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return result
    except Exception as exc:
        logger.debug("_iter_journal_lines: %s", exc)
        return []


def read_signals(limit: int = 50) -> list[dict]:
    """Read last `limit` signal events from TRADE_JOURNAL_FILE."""
    all_lines = _iter_journal_lines()
    signal_lines = [
        line for line in all_lines
        if line.get("event_type") in _SIGNAL_EVENTS
    ]
    # Return most recent first
    return list(reversed(signal_lines))[:limit]


def read_kill_switch() -> dict:
    """Return {active: bool, reason: str}. Safe-fail: returns active=True on error."""
    try:
        raw = KILL_SWITCH_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        active = bool(data.get("active", data.get("triggered", True)))
        reason = data.get("reason") or ""
        return {"active": active, "reason": reason}
    except FileNotFoundError:
        # No kill_switch.json yet — treat as healthy
        return {"active": False, "reason": ""}
    except Exception as exc:
        logger.warning("read_kill_switch: %s — defaulting to BLOCKED", exc)
        return {"active": True, "reason": str(exc)}


def read_accounts() -> list[dict]:
    """Read ACCOUNTS_FILE. Returns sanitized list (no secrets)."""
    _SENSITIVE = {"api_key", "api_secret", "password", "token", "secret",
                  "access_token", "refresh_token", "client_secret"}
    try:
        raw = ACCOUNTS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        accounts = data if isinstance(data, list) else data.get("accounts", [])
        sanitized = []
        for acc in accounts:
            clean = {k: v for k, v in acc.items() if k.lower() not in _SENSITIVE}
            sanitized.append(clean)
        return sanitized
    except Exception as exc:
        logger.debug("read_accounts: %s", exc)
        return []


def read_paused_analysts() -> set[str]:
    """Read PAUSED_FILE. Returns set of analyst_ids."""
    try:
        raw = PAUSED_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        return set(data.get("paused", []))
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Analyst cards
# ---------------------------------------------------------------------------

def read_analyst_cards() -> list[dict]:
    """
    For each of the 12 known analysts compute activity stats from today's journal events.
    Returns list of dicts: {analyst_id, display_name, status, approved_today,
                             rejected_today, last_signal, idle_minutes}
    """
    today_str = date.today().isoformat()
    now = datetime.now(timezone.utc)

    paused_set = read_paused_analysts()
    all_lines  = _iter_journal_lines()

    # Filter to today's events
    today_events = [
        line for line in all_lines
        if line.get("ts", line.get("timestamp", "")).startswith(today_str)
    ]

    # Per-analyst aggregation
    stats: dict[str, dict] = {aid: {"approved": 0, "rejected": 0, "last_ts": None}
                               for aid in ANALYST_DISPLAY_NAMES}

    for event in today_events:
        aid = event.get("analyst_id") or event.get("source") or ""
        if aid not in stats:
            continue
        etype = event.get("event_type", "")
        if etype == "SIGNAL_APPROVED":
            stats[aid]["approved"] += 1
        elif etype == "SIGNAL_REJECTED":
            stats[aid]["rejected"] += 1

        ts_raw = event.get("ts") or event.get("timestamp")
        if ts_raw:
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if stats[aid]["last_ts"] is None or ts > stats[aid]["last_ts"]:
                    stats[aid]["last_ts"] = ts
            except ValueError:
                pass

    cards = []
    for aid, display_name in ANALYST_DISPLAY_NAMES.items():
        s = stats[aid]
        last_ts = s["last_ts"]

        if last_ts is not None:
            idle_minutes = int((now - last_ts).total_seconds() / 60)
        else:
            idle_minutes = None  # no signals at all today

        if aid in paused_set:
            status = "PAUSED"
        elif idle_minutes is None or idle_minutes > 30:
            status = "IDLE"
        else:
            status = "ACTIVE"

        cards.append({
            "analyst_id":      aid,
            "display_name":    display_name,
            "status":          status,
            "approved_today":  s["approved"],
            "rejected_today":  s["rejected"],
            "last_signal":     last_ts.isoformat() if last_ts else None,
            "idle_minutes":    idle_minutes,
        })

    return cards


# ---------------------------------------------------------------------------
# Master aggregator
# ---------------------------------------------------------------------------

def get_all_state() -> dict:
    """Assemble the complete dashboard payload."""
    positions      = read_positions()
    greeks         = read_greeks()
    analyst_cards  = read_analyst_cards()
    ks             = read_kill_switch()
    accounts       = read_accounts()
    paper_mode     = os.getenv("PAPER_TRADING_MODE", "true").lower() == "true"

    # Merge greeks into positions
    for pos in positions:
        pid = pos.get("position_id", "")
        if pid in greeks:
            pos["greeks"] = greeks[pid]

    # Signals for the feed (last 20 for display)
    signals = read_signals(20)

    # Stats for today
    today_str   = date.today().isoformat()
    all_signals = read_signals(200)
    signals_today = [s for s in all_signals if s.get("ts", "").startswith(today_str)]

    total_pnl = sum(
        pos.get("greeks", {}).get("pnl_per_contract", 0) or 0
        for pos in positions
    )

    return {
        "positions":            positions,
        "signals":              signals,
        "analyst_cards":        analyst_cards,
        "kill_switch":          ks,
        "accounts":             accounts,
        "paper_mode":           paper_mode,
        "total_pnl":            total_pnl,
        "open_positions_count": len(positions),
        "approved_today":       sum(1 for s in signals_today
                                    if s.get("event_type") == "SIGNAL_APPROVED"),
        "active_analysts":      sum(1 for a in analyst_cards if a["status"] == "ACTIVE"),
        "updated_at":           datetime.now(timezone.utc).isoformat(),
    }

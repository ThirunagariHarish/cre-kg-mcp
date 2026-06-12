"""
core/logging.py — Structured logging and trade event journal.

All log records are JSON so they can be ingested by Grafana/Loki.
The trade journal is a separate JSONL file — one record per trade event —
designed for post-hoc analysis and RL training.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.file_writer import append_jsonl

_JOURNAL_PATH = Path("shared/state/trade_journal.jsonl")


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Any extra fields attached via logger.info("msg", extra={"foo": "bar"})
        for key, val in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
                "exc_info", "exc_text",
            ):
                payload[key] = val

        import json as _json
        return _json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    """
    Call once at process startup — before anything else.
    json_output=True for production, False for human-readable dev output.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")
        )

    root.handlers.clear()
    root.addHandler(handler)


# ─────────────────────────────────────────────
# Trade event journal
# One append per significant trade lifecycle event.
# Used by Master Analyst's Memory Journal for RL.
# ─────────────────────────────────────────────

class TradeEvent:
    SIGNAL_EMITTED = "SIGNAL_EMITTED"
    SIGNAL_APPROVED = "SIGNAL_APPROVED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"
    HARD_STOP_HIT = "HARD_STOP_HIT"
    KILL_SWITCH_BLOCKED = "KILL_SWITCH_BLOCKED"
    DUPLICATE_SIGNAL_DROPPED = "DUPLICATE_SIGNAL_DROPPED"


def journal(
    event: str,
    analyst_id: str,
    signal_id: str,
    *,
    extra: dict[str, Any] | None = None,
    journal_path: Path = _JOURNAL_PATH,
) -> None:
    """
    Append one trade event to the JSONL journal.
    Non-blocking — any write error is logged but does NOT crash the caller.
    """
    record: dict[str, Any] = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": event,
        "analyst_id": analyst_id,
        "signal_id": signal_id,
    }
    if extra:
        record.update(extra)

    try:
        append_jsonl(journal_path, record)
    except Exception as exc:
        logging.getLogger(__name__).error("Failed to write trade journal: %s", exc)

"""
core/file_writer.py — Atomic file writes.

Legacy lesson: using a shared `.tmp` suffix caused concurrent writers to
corrupt each other's data before the atomic os.replace. Always use
tempfile.mkstemp() which generates a unique temp file per write.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """
    Write JSON to `path` atomically.

    Uses tempfile.mkstemp() in the same directory as `path` so the
    os.replace() is a same-filesystem rename (instant, crash-safe).

    Legacy bug avoided: never use path.with_suffix('.tmp') — shared suffix
    means concurrent writes stomp on each other before the rename.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=indent, default=_json_default)

    # mkstemp creates a unique temp file in the target directory
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, path)  # atomic on POSIX, near-atomic on Windows
    except Exception:
        # Clean up temp file on failure — don't leave debris
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """Write plain text atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """
    Append one JSON record as a line to a .jsonl file.
    Creates the file if it doesn't exist. NOT atomic (append by nature),
    but safe for single-writer use. For multi-writer, use a queue + single writer.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=_json_default)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_json(path: Path, *, default: Any = None) -> Any:
    """Read JSON with a safe fallback. Never raises on missing or malformed file."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("File not found (using default): %s", path)
        return default
    except json.JSONDecodeError as exc:
        logger.error("Malformed JSON in %s: %s (using default)", path, exc)
        return default


def _json_default(obj: Any) -> Any:
    """JSON serialization fallback for common types."""
    from datetime import date, datetime
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

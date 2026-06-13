"""
gateway/dashboard.py — FastAPI dashboard for AnalystTeam system state.

Shows open positions, recent signals, kill-switch status, paper mode indicator.
Plain HTML + Tailwind CDN — no React, no build step required.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Path resolution — works whether run from repo root or scripts/ dir
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STATE_DIR = _REPO_ROOT / "shared" / "state"

KILL_SWITCH_PATH = _STATE_DIR / "kill_switch.json"
OPEN_POSITIONS_PATH = _STATE_DIR / "open_positions.json"
TRADE_JOURNAL_PATH = _STATE_DIR / "trade_journal.jsonl"
MANUAL_CLOSE_QUEUE_PATH = _STATE_DIR / "manual_close_queue.jsonl"

PAPER_MODE: bool = os.getenv("PAPER_TRADING_MODE", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Kill-switch helpers (thin wrappers so we can override path)
# ---------------------------------------------------------------------------

def _ks_is_blocked() -> bool:
    from core.kill_switch import is_blocked
    return is_blocked(KILL_SWITCH_PATH)


def _ks_set_blocked(reason: str) -> None:
    from core.kill_switch import set_blocked
    set_blocked(reason, KILL_SWITCH_PATH)


def _ks_set_healthy() -> None:
    from core.kill_switch import set_healthy
    set_healthy(KILL_SWITCH_PATH)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="AnalystTeam Dashboard", version="1.0.0")

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# State-reading helpers
# ---------------------------------------------------------------------------

def _read_json_list(path: Path) -> list[Any]:
    """Read a JSON file that contains a list. Returns [] on any error."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _read_jsonl_last_n(path: Path, n: int = 50) -> list[dict]:
    """Read last N lines from a .jsonl file. Returns [] on any error."""
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        recent = lines[-n:] if len(lines) > n else lines
        result = []
        for line in recent:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return list(reversed(result))  # newest first
    except Exception:
        return []


def _append_jsonl(path: Path, record: dict) -> None:
    """Atomically append a JSON record to a .jsonl file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class KillSwitchRequest(BaseModel):
    reason: str = "Manually activated via dashboard"


class ManualCloseRequest(BaseModel):
    note: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Render the main dashboard HTML page."""
    blocked = _ks_is_blocked()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "kill_switch_active": blocked,
            "paper_mode": PAPER_MODE,
        },
    )


@app.get("/api/positions")
async def get_positions() -> JSONResponse:
    """Return list of open positions."""
    positions = _read_json_list(OPEN_POSITIONS_PATH)
    return JSONResponse(content=positions)


@app.get("/api/signals")
async def get_signals() -> JSONResponse:
    """Return last 50 signals from trade journal (newest first)."""
    signals = _read_jsonl_last_n(TRADE_JOURNAL_PATH, n=50)
    return JSONResponse(content=signals)


@app.get("/api/health")
async def health() -> JSONResponse:
    """System health — kill-switch state and paper mode."""
    blocked = _ks_is_blocked()
    return JSONResponse(
        content={
            "status": "kill_switch_active" if blocked else "ok",
            "paper_mode": PAPER_MODE,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    )


@app.post("/api/kill-switch/activate")
async def activate_kill_switch(body: KillSwitchRequest) -> JSONResponse:
    """Activate the kill switch with a given reason."""
    try:
        _ks_set_blocked(body.reason)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse(content={"status": "kill_switch_active", "reason": body.reason})


@app.post("/api/kill-switch/deactivate")
async def deactivate_kill_switch() -> JSONResponse:
    """Deactivate the kill switch."""
    try:
        _ks_set_healthy()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse(content={"status": "ok"})


@app.post("/api/positions/{position_id}/close")
async def manual_close_position(position_id: str, body: ManualCloseRequest = ManualCloseRequest()) -> JSONResponse:
    """
    Queue a manual close for a position.
    Writes a record to manual_close_queue.jsonl for the monitor agent to pick up.
    """
    # Verify position exists
    positions = _read_json_list(OPEN_POSITIONS_PATH)
    position = next((p for p in positions if p.get("position_id") == position_id), None)
    if position is None:
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")

    record = {
        "position_id": position_id,
        "requested_at": datetime.utcnow().isoformat() + "Z",
        "reason": "manual_dashboard_close",
        "note": body.note,
        "position_snapshot": position,
    }
    try:
        _append_jsonl(MANUAL_CLOSE_QUEUE_PATH, record)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to queue close: {exc}")

    return JSONResponse(
        content={
            "status": "queued",
            "position_id": position_id,
            "message": "Manual close queued — monitor agent will process it",
        }
    )

"""
gateway/dashboard.py — AnalystTeam Dashboard v2.

FastAPI app with:
  - GET /              → full HTML dashboard (server-side render of initial state)
  - GET /api/state     → JSON snapshot
  - WS  /ws            → real-time push every 5 seconds
  - POST /api/kill-switch/activate|deactivate
  - POST /api/positions/{id}/close
  - POST /api/analysts/{id}/pause|resume
  - GET /api/health
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from gateway.dashboard_state import get_all_state
from core.kill_switch import set_blocked, set_healthy

logger = logging.getLogger(__name__)

app = FastAPI(title="AnalystTeam Dashboard v2", version="2.0.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)
        logger.info("WS client connected — %d active", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
        logger.info("WS client disconnected — %d active", len(self.active))

    async def broadcast(self, data: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self.active[:]:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Background push loop
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    async def push_loop() -> None:
        while True:
            await asyncio.sleep(5)
            if manager.active:
                try:
                    await manager.broadcast(get_all_state())
                except Exception as exc:
                    logger.error("push_loop error: %s", exc)

    asyncio.create_task(push_loop())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    data = get_all_state()
    return templates.TemplateResponse("dashboard.html", {"request": request, **data})


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        # Send initial state immediately on connect
        await websocket.send_json(get_all_state())
        while True:
            # Keep-alive; actual updates come from push_loop
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:
        logger.error("WS error: %s", exc)
        manager.disconnect(websocket)


@app.get("/api/state")
async def api_state() -> JSONResponse:
    return JSONResponse(get_all_state())


@app.post("/api/kill-switch/activate")
async def ks_activate(request: Request) -> JSONResponse:
    body = await request.json()
    reason = body.get("reason", "Activated via dashboard")
    set_blocked(reason)
    await manager.broadcast(get_all_state())
    return JSONResponse({"status": "activated", "reason": reason})


@app.post("/api/kill-switch/deactivate")
async def ks_deactivate() -> JSONResponse:
    set_healthy()
    await manager.broadcast(get_all_state())
    return JSONResponse({"status": "deactivated"})


@app.post("/api/positions/{position_id}/close")
async def close_position(position_id: str) -> JSONResponse:
    from core.file_writer import append_jsonl
    append_jsonl(
        Path("shared/state/manual_close_queue.jsonl"),
        {
            "position_id":   position_id,
            "action":        "close_position",
            "requested_at":  datetime.now(timezone.utc).isoformat(),
        },
    )
    await manager.broadcast(get_all_state())
    return JSONResponse({"status": "queued", "position_id": position_id})


@app.post("/api/analysts/{analyst_id}/pause")
async def pause_analyst(analyst_id: str) -> JSONResponse:
    from gateway.telegram_handler import _load_paused_analysts, _save_paused_analysts
    paused = _load_paused_analysts()
    paused.add(analyst_id)
    _save_paused_analysts(paused)
    await manager.broadcast(get_all_state())
    return JSONResponse({"status": "paused", "analyst_id": analyst_id})


@app.post("/api/analysts/{analyst_id}/resume")
async def resume_analyst(analyst_id: str) -> JSONResponse:
    from gateway.telegram_handler import _load_paused_analysts, _save_paused_analysts
    paused = _load_paused_analysts()
    paused.discard(analyst_id)
    _save_paused_analysts(paused)
    await manager.broadcast(get_all_state())
    return JSONResponse({"status": "resumed", "analyst_id": analyst_id})


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status":     "ok",
        "paper_mode": os.getenv("PAPER_TRADING_MODE", "true").lower() == "true",
        "ws_clients": len(manager.active),
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })

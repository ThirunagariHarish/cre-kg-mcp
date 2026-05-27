"""Agent fleet management — start/stop/restart individual trading agents."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..dependencies import CurrentUser

router = APIRouter(tags=["fleet"])


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Registry: name → agent state
_AGENT_REGISTRY: dict[str, dict[str, Any]] = {
    name: {
        "name": name,
        "display_name": display,
        "category": cat,
        "status": "STOPPED",
        "version": 1,
        "tags": tags,
        "started_at": None,
        "last_heartbeat": None,
        "metrics": {
            "totalSignals": 0,
            "executedTrades": 0,
            "winCount": 0,
            "lossCount": 0,
            "winRate": 0.0,
            "totalPnl": 0.0,
            "todayPnl": 0.0,
            "avgHoldMinutes": 0,
        },
        "logs": [],
        "timeline": [],
    }
    for name, display, cat, tags in [
        ("breakout_trader",        "Breakout Trader",       "ALGORITHM", ["options", "momentum"]),
        ("albert_pro_trader",      "Albert Pro Trader",     "DISCORD",   ["discord", "swing"]),
        ("vcp_setups_trader",      "VCP Setups Trader",     "DISCORD",   ["discord", "breakout"]),
        ("dark_pool_followthrough","Dark Pool Follow",       "ALGORITHM", ["darkpool", "blocks"]),
        ("earnings_momentum",      "Earnings Momentum",     "ALGORITHM", ["earnings", "gap"]),
        ("iron_condor",            "Iron Condor",           "OPTIONS",   ["options", "income"]),
        ("gap_executor",           "Gap & Go Executor",     "ALGORITHM", ["gap", "momentum"]),
        ("discord_ingestor",       "Discord Ingestor",      "DATA",      ["discord", "ingest"]),
        ("ai_analyzer",            "AI Analyzer",           "AI",        ["claude", "analysis"]),
        # ── Unusual Whales live agents ──
        ("uw_flow_scanner",        "UW Flow Scanner",       "ALGORITHM", ["unusual-whales", "sweeps", "options"]),
        ("uw_darkpool_agent",      "UW Dark Pool Agent",    "ALGORITHM", ["unusual-whales", "darkpool"]),
        ("uw_earnings_agent",      "UW Earnings Agent",     "ALGORITHM", ["unusual-whales", "earnings"]),
        ("uw_congress_agent",      "UW Congress Agent",     "ALGORITHM", ["unusual-whales", "congress"]),
        ("uw_short_squeeze",       "UW Short Squeeze",      "ALGORITHM", ["unusual-whales", "short-squeeze"]),
    ]
}


@router.get("/api/fleet", summary="List all agents")
async def list_fleet(_: CurrentUser) -> dict[str, Any]:
    return {"agents": list(_AGENT_REGISTRY.values())}


@router.post("/api/agent/{name}/start", summary="Start an agent")
async def start_agent(name: str, _: CurrentUser) -> dict[str, Any]:
    if name not in _AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent {name} not found")
    agent = _AGENT_REGISTRY[name]
    agent["status"] = "RUNNING"
    agent["started_at"] = _now()
    agent["last_heartbeat"] = _now()
    agent["timeline"].append({"event": "STARTED", "timestamp": _now_iso(), "message": f"Agent {name} started"})
    agent["logs"].append({"level": "INFO", "message": f"Agent {name} started", "timestamp": _now_iso()})
    return agent


@router.post("/api/agent/{name}/stop", summary="Stop an agent")
async def stop_agent(name: str, _: CurrentUser) -> dict[str, Any]:
    if name not in _AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent {name} not found")
    agent = _AGENT_REGISTRY[name]
    agent["status"] = "STOPPED"
    agent["started_at"] = None
    agent["last_heartbeat"] = None
    agent["timeline"].append({"event": "STOPPED", "timestamp": _now_iso(), "message": f"Agent {name} stopped"})
    agent["logs"].append({"level": "INFO", "message": f"Agent {name} stopped", "timestamp": _now_iso()})
    return agent


@router.post("/api/agent/{name}/restart", summary="Restart an agent")
async def restart_agent(name: str, _: CurrentUser) -> dict[str, Any]:
    if name not in _AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent {name} not found")
    agent = _AGENT_REGISTRY[name]
    agent["status"] = "RUNNING"
    agent["started_at"] = _now()
    agent["last_heartbeat"] = _now()
    agent["timeline"].append({"event": "RESTARTED", "timestamp": _now_iso(), "message": f"Agent {name} restarted"})
    agent["logs"].append({"level": "INFO", "message": f"Agent {name} restarted", "timestamp": _now_iso()})
    return agent


@router.get("/api/agent/{name}/logs", summary="Get agent logs")
async def get_agent_logs(name: str, _: CurrentUser, limit: int = 100) -> list[dict[str, Any]]:
    if name not in _AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent {name} not found")
    return _AGENT_REGISTRY[name]["logs"][-limit:]


@router.get("/api/agent/{name}/timeline", summary="Get agent timeline")
async def get_agent_timeline(name: str, _: CurrentUser) -> list[dict[str, Any]]:
    if name not in _AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent {name} not found")
    return _AGENT_REGISTRY[name]["timeline"]


@router.get("/api/agent/{name}/inspect", summary="Get agent config/state")
async def inspect_agent(name: str, _: CurrentUser) -> dict[str, Any]:
    if name not in _AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent {name} not found")
    return _AGENT_REGISTRY[name]

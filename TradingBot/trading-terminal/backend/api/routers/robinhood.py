"""Robinhood execution agent endpoints."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..dependencies import CurrentUser
from ...services.robinhood_execution_service import get_execution_service

router = APIRouter(prefix="/api/robinhood", tags=["robinhood"])


@router.get("/status", summary="Get Robinhood agent status")
async def get_rh_status(_: CurrentUser) -> dict[str, Any]:
    svc = get_execution_service()
    if not svc:
        return {"running": False, "logged_in": False, "paper_mode": True, "queue_depth": 0, "open_positions": 0}
    return await svc.get_status()


@router.get("/positions", summary="Get open positions tracked by execution agent")
async def get_rh_positions(_: CurrentUser) -> list[dict[str, Any]]:
    svc = get_execution_service()
    if not svc:
        return []
    return await svc.get_open_positions()


class TradeRequest(BaseModel):
    agent_id: str = "manual"
    ticker: str
    side: str = "long"
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    quantity: int = 1
    confidence: float = 0.90
    stop_loss_pct: float = 25.0
    take_profit_pct: float = 50.0
    max_position_pct: float = 5.0
    rationale: str = "Manual trade"


@router.post("/execute", summary="Manually enqueue a trade for execution")
async def manual_execute(body: TradeRequest, _: CurrentUser) -> dict[str, Any]:
    svc = get_execution_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Execution service not running")
    msg_id = await svc.enqueue(body.model_dump())
    return {"message_id": msg_id, "status": "queued"}


@router.post("/close/{ticker}", summary="Close a position by ticker")
async def close_position_by_ticker(ticker: str, _: CurrentUser) -> dict[str, Any]:
    svc = get_execution_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Execution service not running")
    await svc.enqueue({"message_type": "CLOSE_POSITION", "ticker": ticker.upper()})
    return {"ticker": ticker.upper(), "status": "close_queued"}


__all__ = ["router"]

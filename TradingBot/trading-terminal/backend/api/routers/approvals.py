"""Pending trade approvals — human-in-the-loop gate for AI/agent orders."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..dependencies import CurrentUser

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_pending: list[dict[str, Any]] = []


class CreateApprovalRequest(BaseModel):
    signal_id: str = ""
    symbol: str = Field(..., min_length=1, max_length=10)
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    qty: float = 0.0
    estimated_value: float = 0.0
    order_type: str = "MARKET"
    limit_price: float | None = None
    portfolio_pct: float = 0.0
    estimated_max_loss: float = 0.0
    raw_signal: str = ""
    agent_name: str = ""


@router.get("/", summary="List pending approvals")
async def list_approvals(_: CurrentUser) -> list[dict[str, Any]]:
    return _pending


@router.post("/", status_code=201, summary="Create approval request")
async def create_approval(body: CreateApprovalRequest, _: CurrentUser) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": f"ap-{uuid.uuid4().hex[:8]}",
        "signalId": body.signal_id,
        "symbol": body.symbol.upper(),
        "direction": body.direction,
        "confidence": body.confidence,
        "qty": body.qty,
        "estimatedValue": body.estimated_value,
        "orderType": body.order_type,
        "limitPrice": body.limit_price,
        "portfolioPct": body.portfolio_pct,
        "estimatedMaxLoss": body.estimated_max_loss,
        "rawSignal": body.raw_signal,
        "agentName": body.agent_name,
        "status": "PENDING",
        "requestedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        "createdAt": _now_iso(),
    }
    _pending.append(entry)
    return entry


@router.post("/{approval_id}/approve", summary="Approve a pending signal")
async def approve_signal(approval_id: str, _: CurrentUser) -> dict[str, Any]:
    for item in _pending:
        if item["id"] == approval_id:
            item["status"] = "APPROVED"
            item["resolvedAt"] = _now_iso()
            return item
    raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")


@router.post("/{approval_id}/reject", summary="Reject a pending signal")
async def reject_signal(approval_id: str, _: CurrentUser) -> dict[str, Any]:
    for item in _pending:
        if item["id"] == approval_id:
            item["status"] = "REJECTED"
            item["resolvedAt"] = _now_iso()
            return item
    raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")

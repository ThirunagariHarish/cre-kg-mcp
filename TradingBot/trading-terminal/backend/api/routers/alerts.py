"""Alert rules management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..dependencies import CurrentUser

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# In-memory alert rules store
_alert_rules: list[dict[str, Any]] = []


class CreateAlertRuleRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    condition: str = Field(..., description="e.g. 'price_above', 'price_below', 'volume_spike'")
    threshold: float
    enabled: bool = True
    notify_channel: str = "websocket"


@router.get("/rules", summary="List alert rules")
async def get_alert_rules(_: CurrentUser) -> list[dict[str, Any]]:
    return _alert_rules


@router.post("/rules", status_code=201, summary="Create alert rule")
async def create_alert_rule(
    body: CreateAlertRuleRequest,
    _: CurrentUser,
) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "rule_id": f"alert-{uuid.uuid4().hex[:8]}",
        "symbol": body.symbol.upper().strip(),
        "condition": body.condition,
        "threshold": body.threshold,
        "enabled": body.enabled,
        "notify_channel": body.notify_channel,
        "created_at": _now_iso(),
        "triggered_count": 0,
    }
    _alert_rules.append(rule)
    return rule


@router.delete("/rules/{rule_id}", summary="Delete alert rule")
async def delete_alert_rule(
    rule_id: str,
    _: CurrentUser,
) -> dict[str, Any]:
    global _alert_rules
    before = len(_alert_rules)
    _alert_rules = [r for r in _alert_rules if r["rule_id"] != rule_id]
    if len(_alert_rules) == before:
        raise HTTPException(status_code=404, detail=f"Alert rule {rule_id} not found")
    return {"rule_id": rule_id, "deleted": True}


@router.patch("/rules/{rule_id}", summary="Toggle alert rule enabled/disabled")
async def toggle_alert_rule(
    rule_id: str,
    _: CurrentUser,
) -> dict[str, Any]:
    for rule in _alert_rules:
        if rule["rule_id"] == rule_id:
            rule["enabled"] = not rule["enabled"]
            return rule
    raise HTTPException(status_code=404, detail=f"Alert rule {rule_id} not found")


__all__ = ["router"]

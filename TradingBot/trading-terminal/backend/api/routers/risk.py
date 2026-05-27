"""Risk management endpoints."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...domain.models import OrderSide
from ...services.risk_service import RiskService
from ...services.ingestion_service import IngestionService
from ..dependencies import get_risk_service, get_ingestion_service, CurrentUser
from ...core.config import get_settings

router = APIRouter(prefix="/api/risk", tags=["risk"])

# In-memory policy override (session-scoped)
_policy_overrides: dict[str, Any] = {}


class EvaluateRequest(BaseModel):
    signal_id: str
    proposed_quantity: float = Field(..., gt=0)
    proposed_entry: float = Field(..., gt=0)


class OverrideRequest(BaseModel):
    override_by: str
    reason: str = Field(..., min_length=5)


class EmergencyStopRequest(BaseModel):
    reason: str = Field(..., min_length=3)


@router.get("/status", summary="Get risk engine status")
async def get_risk_status(
    service: Annotated[RiskService, Depends(get_risk_service)],
    _: CurrentUser,
) -> dict[str, Any]:
    return await service.get_risk_status()


@router.post("/emergency-stop", summary="Activate emergency trading halt")
async def activate_stop(
    body: EmergencyStopRequest,
    service: Annotated[RiskService, Depends(get_risk_service)],
    _: CurrentUser,
) -> dict[str, Any]:
    await service.activate_emergency_stop(body.reason)
    return {"status": "activated", "reason": body.reason}


@router.delete("/emergency-stop", summary="Deactivate emergency trading halt")
async def deactivate_stop(
    service: Annotated[RiskService, Depends(get_risk_service)],
    _: CurrentUser,
) -> dict[str, Any]:
    await service.deactivate_emergency_stop()
    return {"status": "deactivated"}


@router.get("/policy", summary="Get current risk policy")
async def get_policy(_: CurrentUser) -> dict[str, Any]:
    """Return current risk policy settings."""
    settings = get_settings()
    base = {
        "max_position_size_pct": settings.risk_max_position_size_pct,
        "max_portfolio_exposure_pct": settings.risk_max_portfolio_exposure_pct,
        "max_daily_loss_pct": settings.risk_max_daily_loss_pct,
        "min_confidence": settings.risk_min_confidence,
        "min_risk_reward": settings.risk_min_risk_reward,
        "max_open_positions": settings.risk_max_open_positions,
        "blacklisted_symbols": list(settings.blacklisted_symbols_set),
    }
    base.update(_policy_overrides)
    return base


@router.put("/policy", summary="Update risk policy (session-scoped)")
async def update_policy(
    body: dict[str, Any],
    _: CurrentUser,
) -> dict[str, Any]:
    """Update in-memory policy overrides for this session."""
    allowed_keys = {
        "max_position_size_pct", "max_portfolio_exposure_pct",
        "max_daily_loss_pct", "min_confidence", "min_risk_reward",
        "max_open_positions",
    }
    for key in body:
        if key in allowed_keys:
            _policy_overrides[key] = body[key]
    settings = get_settings()
    result = {
        "max_position_size_pct": settings.risk_max_position_size_pct,
        "max_portfolio_exposure_pct": settings.risk_max_portfolio_exposure_pct,
        "max_daily_loss_pct": settings.risk_max_daily_loss_pct,
        "min_confidence": settings.risk_min_confidence,
        "min_risk_reward": settings.risk_min_risk_reward,
        "max_open_positions": settings.risk_max_open_positions,
    }
    result.update(_policy_overrides)
    return result


@router.post("/evaluate", summary="Evaluate a signal for risk")
async def evaluate_signal(
    body: EvaluateRequest,
    risk_service: Annotated[RiskService, Depends(get_risk_service)],
    ingestion: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> dict[str, Any]:
    signal = await ingestion.get_signal(body.signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal {body.signal_id} not found")
    decision = await risk_service.evaluate_signal(signal, body.proposed_quantity, body.proposed_entry)
    return decision.model_dump()


@router.post("/override/{decision_id}", summary="Override a risk decision")
async def override_decision(
    decision_id: str,
    body: OverrideRequest,
    service: Annotated[RiskService, Depends(get_risk_service)],
) -> dict[str, Any]:
    decision = await service.override_decision(decision_id, body.override_by, body.reason)
    return decision.model_dump()

"""Audit trail endpoints."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from ...services.audit_service import AuditService
from ..dependencies import get_audit_service

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/events", summary="Get recent audit events")
async def get_recent_events(
    service: Annotated[AuditService, Depends(get_audit_service)],
    limit: int = Query(100, ge=1, le=1000),
    event_type: str | None = Query(None),
) -> dict[str, Any]:
    events = await service.get_recent_activity(limit=limit, event_type=event_type)
    return {"events": events, "count": len(events)}


@router.get("/aggregate/{aggregate_id}", summary="Get event history for an aggregate")
async def get_aggregate_history(
    aggregate_id: str,
    service: Annotated[AuditService, Depends(get_audit_service)],
    aggregate_type: str | None = Query(None),
) -> dict[str, Any]:
    history = await service.get_history(aggregate_id, aggregate_type)
    return {"aggregate_id": aggregate_id, "events": history, "count": len(history)}

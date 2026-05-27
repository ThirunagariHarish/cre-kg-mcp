"""
Audit service — event-sourced audit trail for all trading activity.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..domain.models import AuditEntry, now_utc
from ..domain.events import DomainEvent
from ..ports.outbound import IEventStore

logger = logging.getLogger(__name__)


class AuditService:
    """
    Maintains an immutable audit trail of all domain events.
    Subscribes to all Kafka topics and stores events for compliance/replay.
    """

    def __init__(self, event_store: IEventStore) -> None:
        self._event_store = event_store
        self._event_count = 0

    async def log_event(
        self,
        event_type: str,
        aggregate_id: str,
        aggregate_type: str,
        payload: dict[str, Any],
        actor: str = "system",
    ) -> AuditEntry:
        """Log a structured audit event."""
        entry = AuditEntry(
            event_type=event_type,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            payload=payload,
            actor=actor,
        )
        # Persist via event store (non-fatal)
        try:
            await self.record_action(
                event_type=event_type,
                aggregate_id=aggregate_id,
                aggregate_type=aggregate_type,
                payload=payload,
                actor=actor,
            )
        except Exception as e:
            logger.warning("Failed to persist audit entry: %s", e)
        self._event_count += 1
        return entry

    async def get_audit_trail(
        self,
        aggregate_id: str | None = None,
        limit: int = 50,
    ) -> list[AuditEntry]:
        """Get audit trail entries."""
        try:
            if aggregate_id:
                events = await self._event_store.get_events(aggregate_id)
            else:
                events = await self._event_store.get_recent_events(limit=limit)
            return [
                AuditEntry(
                    event_type=e.get("event_type", "unknown") if isinstance(e, dict) else e.__class__.__name__,
                    aggregate_id=e.get("aggregate_id", "") if isinstance(e, dict) else e.aggregate_id,
                    aggregate_type=e.get("aggregate_type", "") if isinstance(e, dict) else e.aggregate_type,
                    payload=e if isinstance(e, dict) else e.model_dump(),
                    actor="system",
                )
                for e in events
            ]
        except Exception as e:
            logger.warning("get_audit_trail failed: %s", e)
            return []

    async def record_event(self, event: DomainEvent) -> None:
        """Persist a domain event to the audit log."""
        await self._event_store.append(event)
        self._event_count += 1
        logger.debug(
            "Audit: %s [%s] agg=%s",
            event.__class__.__name__, event.event_id, event.aggregate_id,
        )

    async def record_action(
        self,
        event_type: str,
        aggregate_id: str,
        aggregate_type: str,
        payload: dict[str, Any],
        actor: str = "system",
    ) -> AuditEntry:
        """
        Record a manual or system action that is not already a DomainEvent.
        """
        entry = AuditEntry(
            event_type=event_type,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            payload=payload,
            actor=actor,
        )
        logger.info(
            "Audit action [%s]: %s on %s/%s by %s",
            entry.entry_id, event_type, aggregate_type, aggregate_id, actor,
        )
        return entry

    async def get_history(
        self,
        aggregate_id: str,
        aggregate_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get the complete event history for a single aggregate."""
        events = await self._event_store.get_events(aggregate_id, aggregate_type)
        return [dict(e) if isinstance(e, dict) else e.model_dump() for e in events]

    async def get_recent_activity(
        self,
        limit: int = 100,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get the most recent audit events across all aggregates."""
        return await self._event_store.get_recent_events(limit=limit, event_type=event_type)

    @property
    def event_count(self) -> int:
        return self._event_count


__all__ = ["AuditService"]

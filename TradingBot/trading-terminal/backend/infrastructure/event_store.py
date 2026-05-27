"""
CQRS event store — append-only event log backed by PostgreSQL.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.events import DomainEvent

logger = logging.getLogger(__name__)


class PostgresEventStore:
    """
    Append-only event store backed by the order_events table.
    Provides the foundation for CQRS event sourcing and audit replay.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: DomainEvent) -> None:
        """Append a domain event — immutable, never updated."""
        await self._session.execute(
            text("""
                INSERT INTO order_events (
                    event_id, event_type, aggregate_id, aggregate_type,
                    payload, timestamp, version, correlation_id
                ) VALUES (
                    :event_id, :event_type, :aggregate_id, :aggregate_type,
                    :payload::jsonb, :timestamp, :version, :correlation_id
                )
                ON CONFLICT (event_id) DO NOTHING
            """),
            {
                "event_id": event.event_id,
                "event_type": event.__class__.__name__,
                "aggregate_id": event.aggregate_id,
                "aggregate_type": event.aggregate_type,
                "payload": json.dumps(event.model_dump(), default=str),
                "timestamp": event.timestamp,
                "version": event.version,
                "correlation_id": event.correlation_id,
            },
        )
        await self._session.commit()
        logger.debug("Event stored: %s [%s]", event.__class__.__name__, event.event_id)

    async def get_events(
        self,
        aggregate_id: str,
        aggregate_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve all events for an aggregate in order."""
        query = "SELECT * FROM order_events WHERE aggregate_id = :aggregate_id"
        params: dict[str, Any] = {"aggregate_id": aggregate_id}
        if aggregate_type:
            query += " AND aggregate_type = :aggregate_type"
            params["aggregate_type"] = aggregate_type
        query += " ORDER BY timestamp ASC, version ASC"
        result = await self._session.execute(text(query), params)
        return [dict(row) for row in result.mappings()]

    async def get_recent_events(
        self,
        limit: int = 100,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent events, optionally filtered by type."""
        query = "SELECT * FROM order_events"
        params: dict[str, Any] = {"limit": limit}
        if event_type:
            query += " WHERE event_type = :event_type"
            params["event_type"] = event_type
        query += " ORDER BY timestamp DESC LIMIT :limit"
        result = await self._session.execute(text(query), params)
        return [dict(row) for row in result.mappings()]

    async def count_events(self, aggregate_id: str) -> int:
        """Count events for an aggregate."""
        result = await self._session.execute(
            text("SELECT COUNT(*) FROM order_events WHERE aggregate_id = :aggregate_id"),
            {"aggregate_id": aggregate_id},
        )
        return result.scalar() or 0


__all__ = ["PostgresEventStore"]

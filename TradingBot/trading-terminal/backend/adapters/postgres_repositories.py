"""
PostgreSQL repository implementations using SQLAlchemy 2.x async.
Implements ISignalRepository, IOrderRepository, IPositionRepository.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Signal, Order, Position, OrderSide, OrderType, OrderStatus, AssetClass, PositionStatus, SignalSource, SignalStrength, now_utc
from ..domain.events import DomainEvent

logger = logging.getLogger(__name__)


class PostgresSignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_signal(self, signal: Signal) -> Signal:
        await self._session.execute(
            text("""
                INSERT INTO signals (
                    signal_id, source, symbol, asset_class, direction,
                    raw_message, parsed_text, confidence, strength,
                    suggested_entry, suggested_stop, suggested_target,
                    timeframe, score, metadata, created_at, expires_at
                ) VALUES (
                    :signal_id, :source, :symbol, :asset_class, :direction,
                    :raw_message, :parsed_text, :confidence, :strength,
                    :suggested_entry, :suggested_stop, :suggested_target,
                    :timeframe, :score, :metadata, :created_at, :expires_at
                )
                ON CONFLICT (signal_id) DO UPDATE SET
                    score = EXCLUDED.score,
                    parsed_text = EXCLUDED.parsed_text
            """),
            {
                "signal_id": signal.signal_id,
                "source": signal.source.value,
                "symbol": signal.symbol,
                "asset_class": signal.asset_class.value,
                "direction": signal.direction.value,
                "raw_message": signal.raw_message,
                "parsed_text": signal.parsed_text,
                "confidence": signal.confidence,
                "strength": signal.strength.value,
                "suggested_entry": signal.suggested_entry,
                "suggested_stop": signal.suggested_stop,
                "suggested_target": signal.suggested_target,
                "timeframe": signal.timeframe,
                "score": signal.score,
                "metadata": json.dumps(signal.metadata),
                "created_at": signal.created_at,
                "expires_at": signal.expires_at,
            },
        )
        await self._session.commit()
        return signal

    async def get_signal(self, signal_id: str) -> Signal | None:
        result = await self._session.execute(
            text("SELECT * FROM signals WHERE signal_id = :signal_id"),
            {"signal_id": signal_id},
        )
        row = result.mappings().first()
        if not row:
            return None
        return self._row_to_signal(dict(row))

    async def list_signals(
        self,
        limit: int = 50,
        offset: int = 0,
        symbol: str | None = None,
    ) -> list[Signal]:
        query = "SELECT * FROM signals"
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if symbol:
            query += " WHERE symbol = :symbol"
            params["symbol"] = symbol.upper()
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        result = await self._session.execute(text(query), params)
        return [self._row_to_signal(dict(row)) for row in result.mappings()]

    async def update_signal_score(self, signal_id: str, score: float) -> None:
        await self._session.execute(
            text("UPDATE signals SET score = :score WHERE signal_id = :signal_id"),
            {"signal_id": signal_id, "score": score},
        )
        await self._session.commit()

    def _row_to_signal(self, row: dict[str, Any]) -> Signal:
        return Signal(
            signal_id=row["signal_id"],
            source=SignalSource(row["source"]),
            symbol=row["symbol"],
            asset_class=AssetClass(row["asset_class"]),
            direction=OrderSide(row["direction"]),
            raw_message=row["raw_message"],
            parsed_text=row.get("parsed_text"),
            confidence=float(row["confidence"]),
            strength=SignalStrength(row["strength"]),
            suggested_entry=float(row["suggested_entry"]) if row.get("suggested_entry") else None,
            suggested_stop=float(row["suggested_stop"]) if row.get("suggested_stop") else None,
            suggested_target=float(row["suggested_target"]) if row.get("suggested_target") else None,
            timeframe=row.get("timeframe"),
            score=float(row["score"]) if row.get("score") is not None else None,
            metadata=json.loads(row.get("metadata") or "{}"),
            created_at=row["created_at"],
            expires_at=row.get("expires_at"),
        )


class PostgresOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_order(self, order: Order) -> Order:
        await self._session.execute(
            text("""
                INSERT INTO orders (
                    order_id, signal_id, broker_order_id, symbol, side,
                    order_type, quantity, limit_price, stop_price,
                    time_in_force, status, filled_quantity, average_fill_price,
                    commission, asset_class, metadata, created_at, submitted_at, filled_at
                ) VALUES (
                    :order_id, :signal_id, :broker_order_id, :symbol, :side,
                    :order_type, :quantity, :limit_price, :stop_price,
                    :time_in_force, :status, :filled_quantity, :average_fill_price,
                    :commission, :asset_class, :metadata, :created_at, :submitted_at, :filled_at
                )
                ON CONFLICT (order_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    filled_quantity = EXCLUDED.filled_quantity,
                    average_fill_price = EXCLUDED.average_fill_price,
                    broker_order_id = EXCLUDED.broker_order_id,
                    submitted_at = EXCLUDED.submitted_at,
                    filled_at = EXCLUDED.filled_at
            """),
            {
                "order_id": order.order_id,
                "signal_id": order.signal_id,
                "broker_order_id": order.broker_order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "order_type": order.order_type.value,
                "quantity": order.quantity,
                "limit_price": order.limit_price,
                "stop_price": order.stop_price,
                "time_in_force": order.time_in_force,
                "status": order.status.value,
                "filled_quantity": order.filled_quantity,
                "average_fill_price": order.average_fill_price,
                "commission": order.commission,
                "asset_class": order.asset_class.value,
                "metadata": json.dumps(order.metadata),
                "created_at": order.created_at,
                "submitted_at": order.submitted_at,
                "filled_at": order.filled_at,
            },
        )
        await self._session.commit()
        return order

    async def get_order(self, order_id: str) -> Order | None:
        result = await self._session.execute(
            text("SELECT * FROM orders WHERE order_id = :order_id"),
            {"order_id": order_id},
        )
        row = result.mappings().first()
        if not row:
            return None
        return self._row_to_order(dict(row))

    async def get_order_by_broker_id(self, broker_order_id: str) -> Order | None:
        result = await self._session.execute(
            text("SELECT * FROM orders WHERE broker_order_id = :broker_order_id"),
            {"broker_order_id": broker_order_id},
        )
        row = result.mappings().first()
        if not row:
            return None
        return self._row_to_order(dict(row))

    async def update_order(self, order: Order) -> Order:
        return await self.save_order(order)

    async def list_orders(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Order]:
        query = "SELECT * FROM orders"
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            query += " WHERE status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        result = await self._session.execute(text(query), params)
        return [self._row_to_order(dict(row)) for row in result.mappings()]

    def _row_to_order(self, row: dict[str, Any]) -> Order:
        return Order(
            order_id=row["order_id"],
            signal_id=row.get("signal_id"),
            broker_order_id=row.get("broker_order_id"),
            symbol=row["symbol"],
            side=OrderSide(row["side"]),
            order_type=OrderType(row["order_type"]),
            quantity=float(row["quantity"]),
            limit_price=float(row["limit_price"]) if row.get("limit_price") else None,
            stop_price=float(row["stop_price"]) if row.get("stop_price") else None,
            time_in_force=row["time_in_force"],
            status=OrderStatus(row["status"]),
            filled_quantity=float(row["filled_quantity"]),
            average_fill_price=float(row["average_fill_price"]) if row.get("average_fill_price") else None,
            commission=float(row["commission"]),
            asset_class=AssetClass(row["asset_class"]),
            metadata=json.loads(row.get("metadata") or "{}"),
            created_at=row["created_at"],
            submitted_at=row.get("submitted_at"),
            filled_at=row.get("filled_at"),
        )


class PostgresPositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_position(self, position: Position) -> Position:
        await self._session.execute(
            text("""
                INSERT INTO positions (
                    position_id, symbol, asset_class, side, quantity,
                    avg_entry_price, current_price, realized_pnl,
                    status, metadata, opened_at, closed_at
                ) VALUES (
                    :position_id, :symbol, :asset_class, :side, :quantity,
                    :avg_entry_price, :current_price, :realized_pnl,
                    :status, :metadata, :opened_at, :closed_at
                )
                ON CONFLICT (position_id) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    avg_entry_price = EXCLUDED.avg_entry_price,
                    current_price = EXCLUDED.current_price,
                    realized_pnl = EXCLUDED.realized_pnl,
                    status = EXCLUDED.status,
                    closed_at = EXCLUDED.closed_at
            """),
            {
                "position_id": position.position_id,
                "symbol": position.symbol,
                "asset_class": position.asset_class.value,
                "side": position.side.value,
                "quantity": position.quantity,
                "avg_entry_price": position.avg_entry_price,
                "current_price": position.current_price,
                "realized_pnl": position.realized_pnl,
                "status": position.status.value,
                "metadata": json.dumps(position.metadata),
                "opened_at": position.opened_at,
                "closed_at": position.closed_at,
            },
        )
        await self._session.commit()
        return position

    async def get_position(self, position_id: str) -> Position | None:
        result = await self._session.execute(
            text("SELECT * FROM positions WHERE position_id = :position_id"),
            {"position_id": position_id},
        )
        row = result.mappings().first()
        return self._row_to_position(dict(row)) if row else None

    async def get_position_by_symbol(self, symbol: str) -> Position | None:
        result = await self._session.execute(
            text("SELECT * FROM positions WHERE symbol = :symbol AND status = 'open' ORDER BY opened_at DESC LIMIT 1"),
            {"symbol": symbol.upper()},
        )
        row = result.mappings().first()
        return self._row_to_position(dict(row)) if row else None

    async def update_position(self, position: Position) -> Position:
        return await self.save_position(position)

    async def list_open_positions(self) -> list[Position]:
        result = await self._session.execute(
            text("SELECT * FROM positions WHERE status = 'open' ORDER BY opened_at DESC")
        )
        return [self._row_to_position(dict(row)) for row in result.mappings()]

    async def list_all_positions(self, limit: int = 100) -> list[Position]:
        result = await self._session.execute(
            text("SELECT * FROM positions ORDER BY opened_at DESC LIMIT :limit"),
            {"limit": limit},
        )
        return [self._row_to_position(dict(row)) for row in result.mappings()]

    def _row_to_position(self, row: dict[str, Any]) -> Position:
        return Position(
            position_id=row["position_id"],
            symbol=row["symbol"],
            asset_class=AssetClass(row["asset_class"]),
            side=OrderSide(row["side"]),
            quantity=float(row["quantity"]),
            avg_entry_price=float(row["avg_entry_price"]),
            current_price=float(row["current_price"]) if row.get("current_price") else None,
            realized_pnl=float(row["realized_pnl"]),
            status=PositionStatus(row["status"]),
            metadata=json.loads(row.get("metadata") or "{}"),
            opened_at=row["opened_at"],
            closed_at=row.get("closed_at"),
        )


class PostgresEventStore:
    """CQRS event store — append-only event log."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: DomainEvent) -> None:
        await self._session.execute(
            text("""
                INSERT INTO order_events (
                    event_id, event_type, aggregate_id, aggregate_type,
                    payload, timestamp, version, correlation_id
                ) VALUES (
                    :event_id, :event_type, :aggregate_id, :aggregate_type,
                    :payload, :timestamp, :version, :correlation_id
                )
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

    async def get_events(
        self,
        aggregate_id: str,
        aggregate_type: str | None = None,
    ) -> list[DomainEvent]:
        query = "SELECT * FROM order_events WHERE aggregate_id = :aggregate_id"
        params: dict[str, Any] = {"aggregate_id": aggregate_id}
        if aggregate_type:
            query += " AND aggregate_type = :aggregate_type"
            params["aggregate_type"] = aggregate_type
        query += " ORDER BY timestamp ASC"
        result = await self._session.execute(text(query), params)
        # Return raw dicts — full deserialization would require event registry
        rows = result.mappings().all()
        return [dict(row) for row in rows]  # type: ignore

    async def get_recent_events(
        self,
        limit: int = 100,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM order_events"
        params: dict[str, Any] = {"limit": limit}
        if event_type:
            query += " WHERE event_type = :event_type"
            params["event_type"] = event_type
        query += " ORDER BY timestamp DESC LIMIT :limit"
        result = await self._session.execute(text(query), params)
        return [dict(row) for row in result.mappings()]


__all__ = [
    "PostgresSignalRepository",
    "PostgresOrderRepository",
    "PostgresPositionRepository",
    "PostgresEventStore",
]

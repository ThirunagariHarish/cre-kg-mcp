"""
Domain events — immutable Pydantic v2 models for event-driven architecture.
All trading decisions are captured as events (CQRS/Event Sourcing).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar

from pydantic import BaseModel, Field, ConfigDict

from .models import (
    OrderSide, OrderType, OrderStatus, SignalSource, AssetClass,
    RiskDecisionStatus, now_utc,
)


def _event_id() -> str:
    return str(uuid.uuid4())


class DomainEvent(BaseModel):
    """Base for all domain events. Immutable."""
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_event_id)
    event_type: ClassVar[str] = "domain.event"
    aggregate_id: str
    aggregate_type: str
    timestamp: datetime = Field(default_factory=now_utc)
    version: int = 1
    correlation_id: str | None = None
    causation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_kafka_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.__class__.__name__,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "timestamp": self.timestamp.isoformat(),
            "version": self.version,
            "payload": self.model_dump(exclude={"event_id", "aggregate_id", "aggregate_type", "timestamp", "version"}),
        }


# ─────────────────────── Ingestion Events ───────────────────────

class RawMessageReceived(DomainEvent):
    """Emitted when a raw message arrives from Discord/webhook/news."""
    event_type: ClassVar[str] = "ingestion.raw_message_received"
    aggregate_type: str = "raw_message"

    source: str
    channel_id: str
    author: str
    content: str
    attachments: list[str] = Field(default_factory=list)
    source_message_id: str | None = None


class ParsedTradeIdea(DomainEvent):
    """Emitted after NLP parsing extracts trade intent from raw message."""
    event_type: ClassVar[str] = "parser.trade_idea_parsed"
    aggregate_type: str = "parsed_signal"

    raw_message_id: str
    symbol: str
    direction: OrderSide
    asset_class: AssetClass = AssetClass.EQUITY
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    timeframe: str | None = None
    parser_confidence: float = Field(ge=0.0, le=1.0)
    parser_version: str = "1.0"


class EnrichedSignal(DomainEvent):
    """Emitted after market data enrichment (current price, ATR, volume)."""
    event_type: ClassVar[str] = "enrichment.signal_enriched"
    aggregate_type: str = "enriched_signal"

    parsed_signal_id: str
    symbol: str
    direction: OrderSide
    current_price: float
    volume_24h: float | None = None
    atr: float | None = None
    rsi: float | None = None
    relative_volume: float | None = None
    market_cap: float | None = None
    sector: str | None = None
    enrichment_source: str = "yfinance"


class TradeSignalGenerated(DomainEvent):
    """Emitted after scoring — ready for risk evaluation."""
    event_type: ClassVar[str] = "scorer.trade_signal_generated"
    aggregate_type: str = "trade_signal"

    signal_id: str
    symbol: str
    direction: OrderSide
    asset_class: AssetClass
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_quantity: float
    suggested_entry: float
    suggested_stop: float | None = None
    suggested_target: float | None = None
    source: SignalSource
    reasoning: str | None = None


# ─────────────────────── Risk Events ───────────────────────

class RiskApproved(DomainEvent):
    """Risk gates passed — signal authorized for order creation."""
    event_type: ClassVar[str] = "risk.approved"
    aggregate_type: str = "risk_decision"

    signal_id: str
    approved_quantity: float
    approved_entry: float
    max_loss: float
    portfolio_exposure_pct: float
    checks_passed: list[str] = Field(default_factory=list)
    risk_score: float = Field(ge=0.0, le=1.0, default=0.5)


class RiskRejected(DomainEvent):
    """Risk gates failed — signal blocked from execution."""
    event_type: ClassVar[str] = "risk.rejected"
    aggregate_type: str = "risk_decision"

    signal_id: str
    reason: str
    checks_failed: list[str] = Field(default_factory=list)
    portfolio_exposure_current: float | None = None


# ─────────────────────── Order Events ───────────────────────

class OrderCreated(DomainEvent):
    """Order created in the system (not yet submitted to broker)."""
    event_type: ClassVar[str] = "order.created"
    aggregate_type: str = "order"

    signal_id: str | None = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "day"
    asset_class: AssetClass = AssetClass.EQUITY


class OrderSubmitted(DomainEvent):
    """Order submitted to broker."""
    event_type: ClassVar[str] = "order.submitted"
    aggregate_type: str = "order"

    broker_order_id: str
    broker_name: str
    submitted_at: datetime = Field(default_factory=now_utc)


class OrderFilled(DomainEvent):
    """Order fully or partially filled by broker."""
    event_type: ClassVar[str] = "order.filled"
    aggregate_type: str = "order"

    broker_order_id: str
    filled_quantity: float
    average_fill_price: float
    commission: float = 0.0
    is_partial: bool = False
    filled_at: datetime = Field(default_factory=now_utc)


class OrderCancelled(DomainEvent):
    """Order cancelled (by user or system)."""
    event_type: ClassVar[str] = "order.cancelled"
    aggregate_type: str = "order"

    reason: str = "user_requested"
    cancelled_at: datetime = Field(default_factory=now_utc)


class OrderRejected(DomainEvent):
    """Order rejected by broker."""
    event_type: ClassVar[str] = "order.rejected"
    aggregate_type: str = "order"

    broker_order_id: str | None = None
    reason: str
    error_code: str | None = None


# ─────────────────────── Position Events ───────────────────────

class PositionOpened(DomainEvent):
    """New position opened after order fill."""
    event_type: ClassVar[str] = "position.opened"
    aggregate_type: str = "position"

    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    order_id: str


class PositionClosed(DomainEvent):
    """Position fully or partially closed."""
    event_type: ClassVar[str] = "position.closed"
    aggregate_type: str = "position"

    symbol: str
    closed_quantity: float
    exit_price: float
    realized_pnl: float
    hold_duration_seconds: float
    order_id: str


class PortfolioUpdated(DomainEvent):
    """Portfolio snapshot after any trade activity."""
    event_type: ClassVar[str] = "portfolio.updated"
    aggregate_type: str = "portfolio"

    cash_balance: float
    total_equity: float
    total_market_value: float
    unrealized_pnl: float
    realized_pnl: float
    open_positions_count: int
    position_symbols: list[str] = Field(default_factory=list)


__all__ = [
    "DomainEvent",
    "RawMessageReceived", "ParsedTradeIdea", "EnrichedSignal", "TradeSignalGenerated",
    "RiskApproved", "RiskRejected",
    "OrderCreated", "OrderSubmitted", "OrderFilled", "OrderCancelled", "OrderRejected",
    "PositionOpened", "PositionClosed", "PortfolioUpdated",
]

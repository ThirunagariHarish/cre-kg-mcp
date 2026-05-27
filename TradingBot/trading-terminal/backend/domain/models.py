"""
Core domain models — pure Python/Pydantic, zero infra imports.
Hexagonal architecture: domain is the center, no infrastructure dependencies.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic import ConfigDict


# ─────────────────────────────── Enums ───────────────────────────────

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"

class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"

class SignalSource(str, Enum):
    DISCORD = "discord"
    NEWS = "news"
    TECHNICAL = "technical"
    AI = "ai"
    MANUAL = "manual"
    WEBHOOK = "webhook"

class AssetClass(str, Enum):
    EQUITY = "equity"
    OPTION = "option"
    CRYPTO = "crypto"
    FOREX = "forex"
    FUTURES = "futures"

class RiskDecisionStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"
    MANUAL_REVIEW = "manual_review"

class SignalStrength(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"

class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    PARTIALLY_CLOSED = "partially_closed"


# ─────────────────────────────── Value Objects ───────────────────────────────

class Symbol(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    asset_class: AssetClass = AssetClass.EQUITY

    def __str__(self) -> str:
        return self.ticker.upper()

    @model_validator(mode="after")
    def validate_ticker(self) -> "Symbol":
        if not self.ticker or not self.ticker.strip():
            raise ValueError("ticker cannot be empty")
        object.__setattr__(self, "ticker", self.ticker.upper().strip())
        return self


class Price(BaseModel):
    model_config = ConfigDict(frozen=True)
    amount: Decimal
    currency: str = "USD"

    def __float__(self) -> float:
        return float(self.amount)

    @model_validator(mode="after")
    def validate_positive(self) -> "Price":
        if self.amount < 0:
            raise ValueError("Price cannot be negative")
        return self


class Quantity(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: Decimal

    @model_validator(mode="after")
    def validate_positive(self) -> "Quantity":
        if self.value <= 0:
            raise ValueError("Quantity must be positive")
        return self

    def __float__(self) -> float:
        return float(self.value)


def new_order_id() -> str:
    return f"ord-{uuid.uuid4().hex[:12]}"

def new_signal_id() -> str:
    return f"sig-{uuid.uuid4().hex[:12]}"

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────── Entities ───────────────────────────────

class Signal(BaseModel):
    model_config = ConfigDict(frozen=False)

    signal_id: str = Field(default_factory=new_signal_id)
    source: SignalSource
    symbol: str
    asset_class: AssetClass = AssetClass.EQUITY
    direction: OrderSide
    raw_message: str
    parsed_text: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    strength: SignalStrength = SignalStrength.MODERATE
    suggested_entry: float | None = None
    suggested_stop: float | None = None
    suggested_target: float | None = None
    timeframe: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    expires_at: datetime | None = None
    score: float | None = None


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=False)

    decision_id: str = Field(default_factory=lambda: f"risk-{uuid.uuid4().hex[:12]}")
    signal_id: str
    order_id: str | None = None
    status: RiskDecisionStatus
    reason: str
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    position_size_recommended: float | None = None
    max_loss_allowed: float | None = None
    portfolio_exposure_pct: float | None = None
    created_at: datetime = Field(default_factory=now_utc)


class Order(BaseModel):
    model_config = ConfigDict(frozen=False)

    order_id: str = Field(default_factory=new_order_id)
    signal_id: str | None = None
    broker_order_id: str | None = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "day"
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: float | None = None
    commission: float = 0.0
    asset_class: AssetClass = AssetClass.EQUITY
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    submitted_at: datetime | None = None
    filled_at: datetime | None = None

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED

    @property
    def remaining_quantity(self) -> float:
        return self.quantity - self.filled_quantity

    @property
    def fill_value(self) -> float:
        if self.average_fill_price:
            return self.average_fill_price * self.filled_quantity
        return 0.0


class Position(BaseModel):
    model_config = ConfigDict(frozen=False)

    position_id: str = Field(default_factory=lambda: f"pos-{uuid.uuid4().hex[:12]}")
    symbol: str
    asset_class: AssetClass = AssetClass.EQUITY
    side: OrderSide
    quantity: float
    avg_entry_price: float
    current_price: float | None = None
    realized_pnl: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    opened_at: datetime = Field(default_factory=now_utc)
    closed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def unrealized_pnl(self) -> float:
        if self.current_price is None:
            return 0.0
        if self.side == OrderSide.BUY:
            return (self.current_price - self.avg_entry_price) * self.quantity
        return (self.avg_entry_price - self.current_price) * self.quantity

    @property
    def market_value(self) -> float:
        price = self.current_price or self.avg_entry_price
        return price * self.quantity

    @property
    def total_pnl(self) -> float:
        return self.unrealized_pnl + self.realized_pnl

    @property
    def return_pct(self) -> float:
        cost = self.avg_entry_price * self.quantity
        if cost == 0:
            return 0.0
        return (self.unrealized_pnl / cost) * 100.0


class Portfolio(BaseModel):
    model_config = ConfigDict(frozen=False)

    portfolio_id: str = Field(default_factory=lambda: f"port-{uuid.uuid4().hex[:12]}")
    name: str = "default"
    cash_balance: float = 100_000.0
    positions: dict[str, Position] = Field(default_factory=dict)
    realized_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=now_utc)

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values())

    @property
    def total_equity(self) -> float:
        return self.cash_balance + self.total_market_value

    @property
    def total_pnl(self) -> float:
        return self.total_unrealized_pnl + self.realized_pnl

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol.upper())

    def exposure_pct(self, symbol: str) -> float:
        pos = self.get_position(symbol)
        if not pos or self.total_equity == 0:
            return 0.0
        return (pos.market_value / self.total_equity) * 100.0


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(default_factory=lambda: f"aud-{uuid.uuid4().hex[:12]}")
    event_type: str
    aggregate_id: str
    aggregate_type: str
    payload: dict[str, Any]
    actor: str = "system"
    created_at: datetime = Field(default_factory=now_utc)


__all__ = [
    "OrderSide", "OrderType", "OrderStatus", "SignalSource", "AssetClass",
    "RiskDecisionStatus", "SignalStrength", "PositionStatus",
    "Symbol", "Price", "Quantity",
    "Signal", "RiskDecision", "Order", "Position", "Portfolio", "AuditEntry",
    "new_order_id", "new_signal_id", "now_utc",
]

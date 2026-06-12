"""
core/schemas.py — The single source of truth for all trading data contracts.

Every analyst emits a TradeSignal. Nothing else crosses layer boundaries.
All models are frozen — mutation is a bug, not a feature.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


# ─────────────────────────────────────────────
# Enums (as Literals — no enum overhead)
# ─────────────────────────────────────────────

OptionDirection = Literal["CALL", "PUT"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]
SourceLayer = Literal["DISCORD", "UNUSUAL_WHALES", "SOCIAL", "TECHNICAL", "SCREENER"]
WakeTrigger = Literal["SCHEDULE", "DISCORD_MESSAGE", "MARKET_EVENT"]

ExitStrategy = Literal[
    "FIRST_SELL_FROM_SOURCE",   # Vinod SPX, ADI — close 100% on first sell message
    "PARTIAL_SELL_PCT",          # Vinod other — close partial% on first sell
    "OWNER_FIRST_SELL",          # Zabes — close when owner posts first sell
    "OWNER_LAST_SELL",           # Pilla Swings — close after owner's last sell (10 min silence)
    "MANUAL",                    # Albert, Everest — human closes via dashboard
    "PRICE_TARGET",              # Mag7 — close when price hits multiplier
    "TA_RULES",                  # SPY/SPX UW, Social — Technical Analyst calls the exit
]

SignalStatus = Literal["PENDING", "APPROVED", "REJECTED", "EXECUTED", "CLOSED"]


# ─────────────────────────────────────────────
# Building blocks
# ─────────────────────────────────────────────

class Evidence(BaseModel):
    """One piece of evidence supporting (or questioning) a trade."""

    model_config = ConfigDict(frozen=True)

    indicator: str
    value: Any
    interpretation: str
    # No Field(le=1.0) — we use the validator below so the error message is actionable.
    weight: float
    bullish: bool  # True = supports the trade direction, False = contradicts it

    @field_validator("weight")
    @classmethod
    def weight_is_float(cls, v: float) -> float:
        # Guard against the legacy int-vs-float bug (70 vs 0.70)
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"Evidence weight {v} is outside 0.0–1.0. "
                "Weights must be 0.0–1.0, not percentages. Use 0.70 not 70."
            )
        return v


class OptionContract(BaseModel):
    """A specific option contract to trade. All prices explicitly labeled."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    direction: OptionDirection
    strike: float
    expiry: date

    # Prices — BOTH fields always present to eliminate the per-share vs per-contract bug.
    # per_share = raw market price (e.g. $3.50)
    # per_contract = per_share × 100 (e.g. $350.00)
    bid_per_share: float
    ask_per_share: float
    mark_per_share: float

    open_interest: int
    volume: int
    implied_volatility: float | None = None
    delta: float | None = None

    # computed_field needed in Pydantic v2 frozen models — plain @property is masked by __getattr__
    @computed_field  # type: ignore[misc]
    @property
    def bid_per_contract(self) -> float:
        return self.bid_per_share * 100

    @computed_field  # type: ignore[misc]
    @property
    def ask_per_contract(self) -> float:
        return self.ask_per_share * 100

    @computed_field  # type: ignore[misc]
    @property
    def mark_per_contract(self) -> float:
        return self.mark_per_share * 100

    @computed_field  # type: ignore[misc]
    @property
    def is_tradable(self) -> bool:
        """True if the contract has a market (ask >= $0.10)."""
        return self.ask_per_share >= 0.10

    @field_validator("ask_per_share")
    @classmethod
    def ask_not_penny(cls, v: float) -> float:
        if v < 0.10:
            raise ValueError(
                f"Option ask ${v:.2f} is below $0.10 minimum — penny options are not tradable."
            )
        return v


class ExitRules(BaseModel):
    """How and when to exit a position. Carried with every TradeSignal."""

    model_config = ConfigDict(frozen=True)

    strategy: ExitStrategy

    # PARTIAL_SELL_PCT — fraction to sell on first sell signal (0.70 = 70%)
    partial_sell_pct: float | None = Field(default=None, ge=0.01, le=1.0)

    # PRICE_TARGET — multiplier on entry price (1.05 = 5% gain target)
    price_target_multiplier: float | None = Field(default=None, ge=1.0)

    # FIRST_SELL_FROM_SOURCE / OWNER_FIRST_SELL / OWNER_LAST_SELL
    # Which Discord channel_id to listen to for the sell signal
    source_channel_id: str | None = None

    # OWNER_LAST_SELL — seconds of silence before declaring "last sell" (default 10 min)
    owner_silence_seconds: int = 600

    @model_validator(mode="after")
    def validate_strategy_fields(self) -> "ExitRules":
        if self.strategy == "PARTIAL_SELL_PCT" and self.partial_sell_pct is None:
            raise ValueError("PARTIAL_SELL_PCT strategy requires partial_sell_pct")
        if self.strategy == "PRICE_TARGET" and self.price_target_multiplier is None:
            raise ValueError("PRICE_TARGET strategy requires price_target_multiplier")
        if self.strategy in ("FIRST_SELL_FROM_SOURCE", "OWNER_FIRST_SELL", "OWNER_LAST_SELL"):
            if self.source_channel_id is None:
                raise ValueError(f"{self.strategy} requires source_channel_id")
        return self


# ─────────────────────────────────────────────
# TradeSignal — the one schema that crosses all layer boundaries
# ─────────────────────────────────────────────

class TradeSignal(BaseModel):
    """
    Emitted by every analyst. Consumed by the Master Analyst.
    This is the ONLY object that crosses the analyst → master boundary.
    """

    model_config = ConfigDict(frozen=True)

    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    analyst_id: str          # e.g. "vinod_spx", "mag7", "technical_ta"
    source_layer: SourceLayer
    timestamp: datetime

    symbol: str              # "SPX", "AAPL", "SPY"
    direction: OptionDirection
    strike: float
    expiry: date

    # Price at the moment the signal fired (not the limit price — that's the gateway's job)
    signal_price: float      # per_share, labeled explicitly

    evidence: list[Evidence] = Field(min_length=1)
    risk_level: RiskLevel
    confidence: float  # validated by field_validator below — keeps error message actionable

    exit_rules: ExitRules

    # Raw input that generated this signal (Discord message, UW alert, etc.)
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    # Set by Master Analyst after review
    status: SignalStatus = "PENDING"
    rejection_reason: str | None = None

    @field_validator("confidence")
    @classmethod
    def confidence_is_float(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"Confidence {v} is outside 0.0–1.0. "
                "Must be a fraction, not a percentage. Use 0.75 not 75."
            )
        return v

    @field_validator("symbol")
    @classmethod
    def symbol_uppercase(cls, v: str) -> str:
        return v.upper().strip()

    def evidence_summary(self) -> str:
        """Human-readable evidence for LLM prompts."""
        lines = []
        for e in self.evidence:
            sign = "✓" if e.bullish else "✗"
            lines.append(f"  {sign} [{e.indicator}] {e.interpretation} (weight={e.weight:.2f})")
        return "\n".join(lines)

    def bullish_score(self) -> float:
        """Weighted sum of bullish evidence — used by Master Analyst."""
        total_weight = sum(e.weight for e in self.evidence)
        if total_weight == 0:
            return 0.0
        bullish_weight = sum(e.weight for e in self.evidence if e.bullish)
        return bullish_weight / total_weight


# ─────────────────────────────────────────────
# Execution records (gateway layer)
# ─────────────────────────────────────────────

class OrderRecord(BaseModel):
    """Created by RH Gateway when an order is submitted."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    client_order_id: str       # deterministic hash, used for idempotency
    signal_id: str             # links back to TradeSignal
    analyst_id: str

    symbol: str
    direction: OptionDirection
    strike: float
    expiry: date

    qty: int
    limit_price_per_share: float
    limit_price_per_contract: float  # = limit_price_per_share × 100

    submitted_at: datetime
    status: Literal["SUBMITTED", "FILLED", "PARTIALLY_FILLED", "CANCELLED", "REJECTED"]

    filled_price_per_share: float | None = None
    filled_price_per_contract: float | None = None
    filled_at: datetime | None = None

    paper_mode: bool = True


class PositionRecord(BaseModel):
    """Live open position tracked by Monitor Agent."""

    model_config = ConfigDict(frozen=True)

    position_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str
    signal_id: str
    analyst_id: str

    symbol: str
    direction: OptionDirection
    strike: float
    expiry: date

    qty: int
    avg_cost_per_share: float
    avg_cost_per_contract: float  # = avg_cost_per_share × 100

    opened_at: datetime
    exit_rules: ExitRules

    # Mutable tracking — Monitor Agent updates these
    has_sold_partial: bool = False
    partial_qty_sold: int = 0


# ─────────────────────────────────────────────
# Utility: deterministic client_order_id
# Lesson from legacy: idempotent orders need a stable hash, not random IDs.
# ─────────────────────────────────────────────

def make_client_order_id(
    analyst_id: str,
    action: Literal["BUY", "SELL"],
    symbol: str,
    direction: OptionDirection,
    strike: float,
    expiry: date,
    qty: int,
    trade_date: date,
) -> str:
    """
    SHA-256 hash of all order-identifying fields.
    Same inputs always produce the same client_order_id.
    Redis idempotency cache uses this to prevent duplicate fills on retry.
    """
    raw = f"{analyst_id}|{action}|{symbol}|{direction}|{strike}|{expiry}|{qty}|{trade_date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

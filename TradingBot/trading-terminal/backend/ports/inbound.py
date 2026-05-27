"""
Inbound port interfaces — what the application exposes to the outside world.
These are the use-case contracts that adapters call into.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..domain.models import Signal, Order, Portfolio, RiskDecision
from ..domain.events import RawMessageReceived


@runtime_checkable
class ISignalIngestionPort(Protocol):
    """Port for ingesting raw signals from any source."""

    async def ingest_raw_message(
        self,
        source: str,
        channel_id: str,
        author: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Ingest a raw message. Returns raw_message_id."""
        ...

    async def get_signal(self, signal_id: str) -> Signal | None:
        """Retrieve a signal by ID."""
        ...

    async def list_signals(
        self,
        limit: int = 50,
        offset: int = 0,
        symbol: str | None = None,
    ) -> list[Signal]:
        """List recent signals."""
        ...


@runtime_checkable
class ITradeExecutionPort(Protocol):
    """Port for submitting and managing orders."""

    async def submit_order(self, order: Order) -> Order:
        """Submit an order to the execution layer."""
        ...

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        ...

    async def get_order(self, order_id: str) -> Order | None:
        """Get order by ID."""
        ...

    async def list_orders(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Order]:
        """List orders with optional status filter."""
        ...


@runtime_checkable
class IRiskEvaluationPort(Protocol):
    """Port for evaluating risk of a proposed trade."""

    async def evaluate_signal(
        self,
        signal: Signal,
        proposed_quantity: float,
        proposed_entry: float,
    ) -> RiskDecision:
        """Evaluate risk for a signal. Returns RiskDecision."""
        ...

    async def get_risk_status(self) -> dict[str, Any]:
        """Get current risk engine status and limits."""
        ...

    async def override_decision(
        self,
        decision_id: str,
        override_by: str,
        reason: str,
    ) -> RiskDecision:
        """Manually override a risk decision."""
        ...


@runtime_checkable
class IMarketDataPort(Protocol):
    """Port for retrieving market data."""

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Get current quote for a symbol."""
        ...

    async def get_ohlcv(
        self,
        symbol: str,
        period: str = "1d",
        interval: str = "1m",
    ) -> list[dict[str, Any]]:
        """Get OHLCV bars."""
        ...

    async def get_fundamentals(self, symbol: str) -> dict[str, Any]:
        """Get fundamental data for a symbol."""
        ...


@runtime_checkable
class IAIRecommendationPort(Protocol):
    """Port for AI-powered trade recommendations."""

    async def analyze_signal(
        self,
        signal: Signal,
        market_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyze a signal with AI. Returns recommendation dict."""
        ...

    async def summarize_portfolio(
        self,
        portfolio: Portfolio,
    ) -> str:
        """Generate AI portfolio summary."""
        ...


__all__ = [
    "ISignalIngestionPort",
    "ITradeExecutionPort",
    "IRiskEvaluationPort",
    "IMarketDataPort",
    "IAIRecommendationPort",
]

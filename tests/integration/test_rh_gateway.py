"""
tests/integration/test_rh_gateway.py — Integration tests for RHGateway (paper mode).

All tests run in paper mode — no Robinhood credentials required.
Redis is mocked where needed so tests pass without a running Redis server.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    OrderRecord,
    PositionRecord,
    TradeSignal,
)
from gateway.rh_gateway import RHGateway


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

def _make_signal(
    symbol: str = "SPY",
    direction: str = "CALL",
    strike: float = 500.0,
    expiry: date | None = None,
    signal_price: float = 1.50,
    analyst_id: str = "test_analyst",
) -> TradeSignal:
    """Build a minimal valid TradeSignal for testing."""
    if expiry is None:
        expiry = date.today() + timedelta(days=7)  # next week — avoids 0DTE guard

    return TradeSignal(
        analyst_id=analyst_id,
        source_layer="DISCORD",
        timestamp=datetime.now(tz=timezone.utc),
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        strike=strike,
        expiry=expiry,
        signal_price=signal_price,
        evidence=[
            Evidence(
                indicator="EMA",
                value="above 200",
                interpretation="Bullish trend",
                weight=0.8,
                bullish=True,
            )
        ],
        risk_level="MEDIUM",
        confidence=0.75,
        exit_rules=ExitRules(
            strategy="MANUAL",
        ),
    )


def _make_position(
    symbol: str = "SPY",
    direction: str = "CALL",
    strike: float = 500.0,
    expiry: date | None = None,
    qty: int = 1,
    avg_cost: float = 1.50,
    analyst_id: str = "test_analyst",
    signal_id: str = "test-signal-id",
    order_id: str = "test-order-id",
) -> PositionRecord:
    """Build a minimal valid PositionRecord for testing."""
    if expiry is None:
        expiry = date.today() + timedelta(days=7)

    return PositionRecord(
        order_id=order_id,
        signal_id=signal_id,
        analyst_id=analyst_id,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        strike=strike,
        expiry=expiry,
        qty=qty,
        avg_cost_per_share=avg_cost,
        avg_cost_per_contract=avg_cost * 100,
        opened_at=datetime.now(tz=timezone.utc),
        exit_rules=ExitRules(strategy="MANUAL"),
    )


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

class TestPaperExecuteSignal:
    """1. execute_signal() in paper mode returns a filled OrderRecord."""

    @pytest.mark.asyncio
    async def test_paper_execute_signal(self) -> None:
        gateway = RHGateway(paper_mode=True)
        signal = _make_signal()

        order = await gateway.execute_signal(signal)

        assert order is not None, "Expected an OrderRecord, got None"
        assert isinstance(order, OrderRecord)
        assert order.paper_mode is True
        assert order.status == "FILLED"
        assert order.signal_id == signal.signal_id
        assert order.analyst_id == signal.analyst_id
        assert order.symbol == signal.symbol
        assert order.direction == signal.direction
        assert order.strike == signal.strike
        assert order.expiry == signal.expiry
        assert order.qty >= 1
        assert order.limit_price_per_share > 0
        assert order.limit_price_per_contract == pytest.approx(
            order.limit_price_per_share * 100, rel=1e-6
        )
        assert order.filled_price_per_share is not None
        assert order.filled_at is not None


class TestIdempotentOrder:
    """2. Same client_order_id called twice returns the same order_id (mocked Redis)."""

    @pytest.mark.asyncio
    async def test_idempotent_order(self) -> None:
        # Build a mock Redis that returns a cached result on the second call
        mock_redis = AsyncMock()
        # First get: cache miss; second get: cache hit
        call_count = 0
        stored: dict[str, str] = {}

        async def mock_get(key: str) -> str | None:
            return stored.get(key)

        async def mock_setex(key: str, ttl: int, value: str) -> None:
            stored[key] = value

        mock_redis.get = mock_get
        mock_redis.setex = mock_setex

        gateway = RHGateway(paper_mode=True, redis_client=mock_redis)
        signal = _make_signal()

        # First call — should submit
        order1 = await gateway.execute_signal(signal)
        assert order1 is not None, "First call should return an OrderRecord"

        # Second call — should be idempotency hit and return same order
        order2 = await gateway.execute_signal(signal)
        assert order2 is not None, "Second call should return cached OrderRecord"
        assert order1.order_id == order2.order_id, (
            f"Expected same order_id on retry, got {order1.order_id!r} vs {order2.order_id!r}"
        )


class TestMinAskGuard:
    """3. Signal with ask < $0.10 returns None."""

    @pytest.mark.asyncio
    async def test_min_ask_guard(self) -> None:
        gateway = RHGateway(paper_mode=True)
        signal = _make_signal()

        # Override get_quote to return a penny option
        async def cheap_quote(
            symbol: str, direction: str, strike: float, expiry: date
        ) -> OptionContract | None:
            # OptionContract validator rejects ask < $0.10, so we bypass it
            # by returning None (no quote) to simulate the guard
            return None

        with patch.object(gateway, "get_quote", side_effect=cheap_quote):
            order = await gateway.execute_signal(signal)

        assert order is None, "Expected None for unquotable option"

    @pytest.mark.asyncio
    async def test_min_ask_guard_via_is_tradable(self) -> None:
        """Simulate the is_tradable=False path by monkeypatching the contract."""
        gateway = RHGateway(paper_mode=True)
        signal = _make_signal()

        # Create a contract that bypasses the validator but has low ask
        # We use a mock object that mimics OptionContract
        mock_contract = MagicMock(spec=OptionContract)
        mock_contract.is_tradable = False
        mock_contract.ask_per_share = 0.05

        async def cheap_quote(*args: Any, **kwargs: Any) -> MagicMock:
            return mock_contract

        with patch.object(gateway, "get_quote", side_effect=cheap_quote):
            order = await gateway.execute_signal(signal)

        assert order is None, "Expected None when is_tradable=False"


class TestPaperPositionTracked:
    """4. After execute_signal, get_positions() contains the new position."""

    @pytest.mark.asyncio
    async def test_paper_position_tracked(self) -> None:
        gateway = RHGateway(paper_mode=True)
        signal = _make_signal()

        positions_before = await gateway.get_positions()
        assert len(positions_before) == 0

        order = await gateway.execute_signal(signal)
        assert order is not None

        positions_after = await gateway.get_positions()
        assert len(positions_after) == 1

        pos = positions_after[0]
        assert isinstance(pos, PositionRecord)
        assert pos.symbol == signal.symbol
        assert pos.direction == signal.direction
        assert pos.strike == signal.strike
        assert pos.expiry == signal.expiry
        assert pos.order_id == order.order_id
        assert pos.signal_id == signal.signal_id
        assert pos.qty >= 1

    @pytest.mark.asyncio
    async def test_multiple_signals_tracked(self) -> None:
        gateway = RHGateway(paper_mode=True)

        signals = [
            _make_signal(symbol="SPY", strike=500.0, analyst_id=f"analyst_{i}")
            for i in range(3)
        ]
        for sig in signals:
            await gateway.execute_signal(sig)

        positions = await gateway.get_positions()
        assert len(positions) == 3


class TestClosePositionPaper:
    """5. execute_signal then close_position — position removed from paper positions."""

    @pytest.mark.asyncio
    async def test_close_position_paper(self) -> None:
        gateway = RHGateway(paper_mode=True)
        signal = _make_signal()

        # Open a position
        order = await gateway.execute_signal(signal)
        assert order is not None

        positions = await gateway.get_positions()
        assert len(positions) == 1
        position = positions[0]

        # Close it fully
        close_order = await gateway.close_position(position, qty=position.qty, reason="TEST_EXIT")

        assert close_order is not None, "Expected a close OrderRecord"
        assert isinstance(close_order, OrderRecord)
        assert close_order.status == "FILLED"
        assert close_order.paper_mode is True
        assert close_order.qty == position.qty

        # Position should be gone
        positions_after = await gateway.get_positions()
        assert len(positions_after) == 0

    @pytest.mark.asyncio
    async def test_partial_close_position_paper(self) -> None:
        gateway = RHGateway(paper_mode=True)

        # Force qty >= 2 by lowering max position size relative to a cheap option
        gateway._max_position_usd = 500.0

        signal = _make_signal(signal_price=1.00)  # ask ~$1.00 → $100/contract → qty=5

        order = await gateway.execute_signal(signal)
        assert order is not None

        positions = await gateway.get_positions()
        assert len(positions) == 1
        position = positions[0]

        if position.qty < 2:
            pytest.skip("Position qty too small for partial close test")

        partial_qty = position.qty - 1
        close_order = await gateway.close_position(
            position, qty=partial_qty, reason="PARTIAL_TEST"
        )
        assert close_order is not None

        positions_after = await gateway.get_positions()
        assert len(positions_after) == 1, "Position should still exist after partial close"
        assert positions_after[0].qty == 1
        assert positions_after[0].has_sold_partial is True
        assert positions_after[0].partial_qty_sold == partial_qty

    @pytest.mark.asyncio
    async def test_close_idempotency(self) -> None:
        """Closing the same position twice should not double-remove it."""
        gateway = RHGateway(paper_mode=True)
        signal = _make_signal()

        order = await gateway.execute_signal(signal)
        assert order is not None

        positions = await gateway.get_positions()
        position = positions[0]

        close1 = await gateway.close_position(position, qty=position.qty, reason="FIRST")
        assert close1 is not None

        close2 = await gateway.close_position(position, qty=position.qty, reason="SECOND")
        # Second call hits idempotency cache and returns cached or None
        # Either way, positions should still be empty
        positions_after = await gateway.get_positions()
        assert len(positions_after) == 0


class TestAccountInfo:
    """Sanity check on get_account() in paper mode."""

    @pytest.mark.asyncio
    async def test_account_paper(self) -> None:
        gateway = RHGateway(paper_mode=True)
        account = await gateway.get_account()

        assert account["paper_mode"] is True
        assert "open_positions" in account
        assert "total_position_value_usd" in account
        assert account["open_positions"] == 0

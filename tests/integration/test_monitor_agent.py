"""
tests/integration/test_monitor_agent.py — MonitorAgent integration tests.

All tests use mocked gateway (no live RH API, no Telegram).
Covers: hard stop-loss, hard take-profit, FIRST_SELL_FROM_SOURCE,
PARTIAL_SELL_PCT, MANUAL (no auto-close), and market close sweep.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.schemas import ExitRules, PositionRecord
from gateway.monitor_agent import MonitorAgent


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

CHANNEL_ID = "ch_test_001"


def _make_position(
    *,
    avg_cost_per_share: float = 3.00,
    qty: int = 10,
    strategy: str = "FIRST_SELL_FROM_SOURCE",
    partial_sell_pct: float | None = None,
    price_target_multiplier: float | None = None,
    source_channel_id: str | None = CHANNEL_ID,
    has_sold_partial: bool = False,
    partial_qty_sold: int = 0,
) -> PositionRecord:
    exit_rules_kwargs: dict[str, Any] = {
        "strategy": strategy,
        "source_channel_id": source_channel_id,
    }
    if partial_sell_pct is not None:
        exit_rules_kwargs["partial_sell_pct"] = partial_sell_pct
    if price_target_multiplier is not None:
        exit_rules_kwargs["price_target_multiplier"] = price_target_multiplier

    return PositionRecord(
        order_id="ord_001",
        signal_id="sig_001",
        analyst_id="test_analyst",
        symbol="SPX",
        direction="CALL",
        strike=5000.0,
        expiry=date(2026, 7, 18),
        qty=qty,
        avg_cost_per_share=avg_cost_per_share,
        avg_cost_per_contract=avg_cost_per_share * 100,
        opened_at=datetime.now(tz=timezone.utc),
        exit_rules=ExitRules(**exit_rules_kwargs),
        has_sold_partial=has_sold_partial,
        partial_qty_sold=partial_qty_sold,
    )


def _make_gateway(quote_price: float | None = None) -> MagicMock:
    """Create a mock RHGateway."""
    gw = MagicMock()
    gw.paper_mode = True
    gw.get_quote = AsyncMock(return_value=quote_price)
    gw.close_position = AsyncMock(return_value=True)
    return gw


def _make_agent(
    gateway: MagicMock,
    sell_queues: dict[str, asyncio.Queue] | None = None,
) -> MonitorAgent:
    agent = MonitorAgent(
        gateway=gateway,
        sell_queues=sell_queues or {},
        poll_interval_seconds=30,
    )
    # Suppress Telegram (no env vars)
    agent._tg_token = ""
    agent._tg_chat_id = ""
    return agent


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

class TestHardStops:
    async def test_hard_stop_loss_triggers(self) -> None:
        """Position at -55% loss triggers hard stop-loss close."""
        avg_cost = 3.00
        current_price = avg_cost * (1 + MonitorAgent.HARD_STOP_LOSS_PCT - 0.05)  # -55%

        gw = _make_gateway(quote_price=current_price)
        agent = _make_agent(gw)
        pos = _make_position(avg_cost_per_share=avg_cost, strategy="MANUAL")
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        closed = await agent._check_hard_stops(pos, current_price)

        assert closed is True
        gw.close_position.assert_called_once()
        call_args = gw.close_position.call_args
        assert call_args[0][0] is pos
        assert call_args[0][1] == pos.qty  # full qty
        assert "HARD_STOP_LOSS" in call_args[0][2]
        # Position removed from tracking
        assert pos.position_id not in agent._positions

    async def test_hard_take_profit_triggers(self) -> None:
        """Position at +110% gain triggers hard take-profit close."""
        avg_cost = 3.00
        current_price = avg_cost * (1 + MonitorAgent.HARD_TAKE_PROFIT_PCT + 0.10)  # +110%

        gw = _make_gateway(quote_price=current_price)
        agent = _make_agent(gw)
        pos = _make_position(avg_cost_per_share=avg_cost, strategy="MANUAL")
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        closed = await agent._check_hard_stops(pos, current_price)

        assert closed is True
        gw.close_position.assert_called_once()
        call_args = gw.close_position.call_args
        assert "HARD_TAKE_PROFIT" in call_args[0][2]
        assert pos.position_id not in agent._positions

    async def test_no_hard_stop_within_bounds(self) -> None:
        """Position at -30% loss does NOT trigger hard stop."""
        avg_cost = 3.00
        current_price = avg_cost * 0.70  # -30%

        gw = _make_gateway(quote_price=current_price)
        agent = _make_agent(gw)
        pos = _make_position(avg_cost_per_share=avg_cost)
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        closed = await agent._check_hard_stops(pos, current_price)

        assert closed is False
        gw.close_position.assert_not_called()


class TestFirstSellFromSource:
    async def test_first_sell_from_source_closes(self) -> None:
        """Sell message on queue -> position closed 100%."""
        sell_q: asyncio.Queue[dict] = asyncio.Queue()
        await sell_q.put({"type": "sell", "content": "Sold SPX 5000C"})

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw, sell_queues={CHANNEL_ID: sell_q})

        pos = _make_position(strategy="FIRST_SELL_FROM_SOURCE")
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        await agent._handle_first_sell(pos)

        gw.close_position.assert_called_once()
        call_args = gw.close_position.call_args
        assert call_args[0][1] == pos.qty  # full qty
        assert "FIRST_SELL_FROM_SOURCE" in call_args[0][2]
        assert pos.position_id not in agent._positions

    async def test_no_sell_message_no_close(self) -> None:
        """Empty queue -> position NOT closed."""
        sell_q: asyncio.Queue[dict] = asyncio.Queue()  # empty

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw, sell_queues={CHANNEL_ID: sell_q})

        pos = _make_position(strategy="FIRST_SELL_FROM_SOURCE")
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        await agent._handle_first_sell(pos)

        gw.close_position.assert_not_called()
        assert pos.position_id in agent._positions

    async def test_owner_first_sell_closes(self) -> None:
        """OWNER_FIRST_SELL behaves identically to FIRST_SELL_FROM_SOURCE."""
        sell_q: asyncio.Queue[dict] = asyncio.Queue()
        await sell_q.put({"type": "sell", "content": "out"})

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw, sell_queues={CHANNEL_ID: sell_q})

        pos = _make_position(strategy="OWNER_FIRST_SELL")
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        await agent._handle_first_sell(pos)

        gw.close_position.assert_called_once()
        assert pos.position_id not in agent._positions


class TestPartialSell:
    async def test_partial_sell_first_sell_closes_70_pct(self) -> None:
        """PARTIAL_SELL_PCT: first sell message closes 70%, position stays open."""
        sell_q: asyncio.Queue[dict] = asyncio.Queue()
        await sell_q.put({"type": "sell", "content": "selling partial"})

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw, sell_queues={CHANNEL_ID: sell_q})

        pos = _make_position(
            qty=10,
            strategy="PARTIAL_SELL_PCT",
            partial_sell_pct=0.70,
        )
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        await agent._handle_partial_sell(pos)

        gw.close_position.assert_called_once()
        call_args = gw.close_position.call_args
        assert call_args[0][1] == 7  # 70% of 10
        assert "first sell" in call_args[0][2]

        # Position still tracked (only partial close)
        assert pos.position_id in agent._positions
        pstate = agent._partial_state[pos.position_id]
        assert pstate["has_sold_partial"] is True
        assert pstate["partial_qty_sold"] == 7

    async def test_partial_sell_second_sell_closes_remainder(self) -> None:
        """PARTIAL_SELL_PCT: second sell message closes remaining 30%."""
        sell_q: asyncio.Queue[dict] = asyncio.Queue()
        await sell_q.put({"type": "sell", "content": "closing rest"})

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw, sell_queues={CHANNEL_ID: sell_q})

        pos = _make_position(
            qty=10,
            strategy="PARTIAL_SELL_PCT",
            partial_sell_pct=0.70,
        )
        agent._positions[pos.position_id] = pos
        # Simulate already having done the first partial sell
        agent._partial_state[pos.position_id] = {
            "has_sold_partial": True,
            "partial_qty_sold": 7,
        }

        await agent._handle_partial_sell(pos)

        gw.close_position.assert_called_once()
        call_args = gw.close_position.call_args
        assert call_args[0][1] == 3  # remaining 30%
        assert "remainder" in call_args[0][2]
        # Position fully closed
        assert pos.position_id not in agent._positions

    async def test_partial_sell_full_flow(self) -> None:
        """Full PARTIAL_SELL_PCT flow: two sell messages -> position fully closed."""
        sell_q: asyncio.Queue[dict] = asyncio.Queue()

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw, sell_queues={CHANNEL_ID: sell_q})

        pos = _make_position(
            qty=10,
            strategy="PARTIAL_SELL_PCT",
            partial_sell_pct=0.70,
        )
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        # First sell
        await sell_q.put({"type": "sell", "content": "first sell"})
        await agent._handle_partial_sell(pos)
        assert gw.close_position.call_count == 1
        assert pos.position_id in agent._positions  # still open

        # Second sell
        await sell_q.put({"type": "sell", "content": "second sell"})
        await agent._handle_partial_sell(pos)
        assert gw.close_position.call_count == 2
        assert pos.position_id not in agent._positions  # fully closed

        # Verify qty breakdown: 7 + 3 = 10
        first_call_qty = gw.close_position.call_args_list[0][0][1]
        second_call_qty = gw.close_position.call_args_list[1][0][1]
        assert first_call_qty == 7
        assert second_call_qty == 3


class TestManualNoAutoClose:
    async def test_manual_no_auto_close_on_sell_message(self) -> None:
        """MANUAL strategy: even with sell message in queue, position is NOT auto-closed."""
        sell_q: asyncio.Queue[dict] = asyncio.Queue()
        await sell_q.put({"type": "sell", "content": "sell everything"})

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw, sell_queues={CHANNEL_ID: sell_q})

        pos = _make_position(
            strategy="MANUAL",
            source_channel_id=None,  # MANUAL doesn't need source_channel_id
        )
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        # Run check_position (not just a specific handler)
        with patch.object(agent, "_get_price", return_value=3.00):
            await agent._check_position(pos)

        gw.close_position.assert_not_called()
        assert pos.position_id in agent._positions
        # Queue still has the message (wasn't drained by MANUAL handler)
        assert not sell_q.empty()

    async def test_manual_hard_stop_still_fires(self) -> None:
        """MANUAL strategy does NOT bypass hard stops."""
        avg_cost = 3.00
        current_price = avg_cost * 0.40  # -60% -> below hard stop

        gw = _make_gateway(quote_price=current_price)
        agent = _make_agent(gw)

        pos = _make_position(
            avg_cost_per_share=avg_cost,
            strategy="MANUAL",
            source_channel_id=None,
        )
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        with patch.object(agent, "_get_price", return_value=current_price):
            await agent._check_position(pos)

        gw.close_position.assert_called_once()
        assert "HARD_STOP_LOSS" in gw.close_position.call_args[0][2]


class TestMarketCloseSweep:
    async def test_market_close_sweep_closes_all_positions(self) -> None:
        """At 3:56 PM ET (4 min before close), all positions are swept closed."""
        from zoneinfo import ZoneInfo

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw)

        # Add two positions
        pos1 = _make_position(qty=5)
        pos2 = _make_position(qty=3)
        for pos in (pos1, pos2):
            agent._positions[pos.position_id] = pos
            agent._partial_state[pos.position_id] = {
                "has_sold_partial": False,
                "partial_qty_sold": 0,
            }

        # Mock datetime to 3:56 PM ET (4 min before close, within 5 min sweep window)
        et = ZoneInfo("America/New_York")
        mock_now = datetime(2026, 6, 13, 15, 56, 0, tzinfo=et)

        with patch("gateway.monitor_agent.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now

            await agent._check_market_close()

        assert gw.close_position.call_count == 2
        # Both positions removed
        assert pos1.position_id not in agent._positions
        assert pos2.position_id not in agent._positions

        # Verify reason contains sweep
        for call in gw.close_position.call_args_list:
            assert "MARKET_CLOSE_SWEEP" in call[0][2]

    async def test_market_close_sweep_not_triggered_early(self) -> None:
        """At 3:50 PM ET (10 min before close), sweep does NOT fire."""
        from zoneinfo import ZoneInfo

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw)

        pos = _make_position(qty=5)
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        et = ZoneInfo("America/New_York")
        mock_now = datetime(2026, 6, 13, 15, 50, 0, tzinfo=et)

        with patch("gateway.monitor_agent.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now

            await agent._check_market_close()

        gw.close_position.assert_not_called()
        assert pos.position_id in agent._positions

    async def test_market_close_sweep_exactly_at_boundary(self) -> None:
        """At exactly 3:55 PM ET (exactly 5 min before close), sweep fires."""
        from zoneinfo import ZoneInfo

        gw = _make_gateway(quote_price=3.00)
        agent = _make_agent(gw)

        pos = _make_position(qty=2)
        agent._positions[pos.position_id] = pos
        agent._partial_state[pos.position_id] = {"has_sold_partial": False, "partial_qty_sold": 0}

        et = ZoneInfo("America/New_York")
        mock_now = datetime(2026, 6, 13, 15, 55, 0, tzinfo=et)

        with patch("gateway.monitor_agent.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now

            await agent._check_market_close()

        gw.close_position.assert_called_once()


class TestDrainSellQueue:
    async def test_drain_returns_all_queued_messages(self) -> None:
        """_drain_sell_queue returns all pending messages non-blocking."""
        sell_q: asyncio.Queue[dict] = asyncio.Queue()
        msgs = [{"id": i} for i in range(5)]
        for m in msgs:
            await sell_q.put(m)

        gw = _make_gateway()
        agent = _make_agent(gw, sell_queues={CHANNEL_ID: sell_q})

        result = await agent._drain_sell_queue(CHANNEL_ID)

        assert len(result) == 5
        assert sell_q.empty()

    async def test_drain_empty_queue_returns_empty_list(self) -> None:
        """Empty queue returns []."""
        sell_q: asyncio.Queue[dict] = asyncio.Queue()
        gw = _make_gateway()
        agent = _make_agent(gw, sell_queues={CHANNEL_ID: sell_q})

        result = await agent._drain_sell_queue(CHANNEL_ID)
        assert result == []

    async def test_drain_unknown_channel_returns_empty(self) -> None:
        """Unknown channel_id returns [] without error."""
        gw = _make_gateway()
        agent = _make_agent(gw, sell_queues={})

        result = await agent._drain_sell_queue("nonexistent_channel")
        assert result == []

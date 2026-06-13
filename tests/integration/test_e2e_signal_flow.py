"""
tests/integration/test_e2e_signal_flow.py

End-to-end signal flow tests.
Discord message dict → analyst._process() → TradeSignal on queue.

No live Discord connection. No Redis. No RH API.
Drives the actual async code paths the gateway uses.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from analysts.discord.vinod import VinodSPXAnalyst, VinodOtherAnalyst
from core.base_analyst import WakeEvent
from core.kill_switch import set_blocked, set_healthy
from core.sanitizer import sanitize
from core.schemas import TradeSignal

SPX_CHANNEL   = "1495516216645783562"
OTHER_CHANNEL = "1495516626647519343"
KILL_SWITCH   = Path("shared/state/kill_switch.json")


def _msg(content: str, channel_id: str, author: str = "INFRA TRADE ALERT", is_bot: bool = True) -> dict:
    return {
        "message_id": "test001",
        "channel_id": channel_id,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "author_id": "9001",
        "author_name": author,
        "author_global_name": author,
        "is_bot": is_bot,
        "content_raw": content,
        "content": sanitize(content).text,
        "embeds": [],
    }


async def _process_one(analyst: VinodSPXAnalyst | VinodOtherAnalyst, msg: dict) -> None:
    """Inject a single message into the analyst and process it synchronously."""
    event = WakeEvent(trigger="DISCORD_MESSAGE", raw=msg, channel_id=msg["channel_id"])
    await analyst.wake(event)


# ─── VinodSPXAnalyst ──────────────────────────────────────────────────────────

class TestVinodSPXE2E:
    @pytest.fixture
    def signal_queue(self) -> "asyncio.Queue[TradeSignal]":
        return asyncio.Queue()

    @pytest.fixture
    def analyst(self, signal_queue: "asyncio.Queue[TradeSignal]") -> VinodSPXAnalyst:
        a = VinodSPXAnalyst(signal_queue=signal_queue, channel_id=SPX_CHANNEL)
        a._running = True
        return a

    async def test_spx_call_buy_produces_correct_signal(
        self, analyst: VinodSPXAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        msg = _msg("**SPX :** Bought SPX 7550C at 3.50 Small Trade above 7500", SPX_CHANNEL)
        await _process_one(analyst, msg)

        assert not signal_queue.empty()
        sig = signal_queue.get_nowait()
        assert sig.symbol == "SPX"
        assert sig.direction == "CALL"
        assert sig.strike == 7550.0
        assert sig.signal_price == 3.50
        assert sig.analyst_id == "vinod_spx"
        assert sig.exit_rules.strategy == "FIRST_SELL_FROM_SOURCE"
        assert sig.exit_rules.source_channel_id == SPX_CHANNEL
        assert sig.confidence == 0.80
        assert sig.status == "PENDING"

    async def test_spx_put_buy(
        self, analyst: VinodSPXAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        msg = _msg("**SPX :** Bought SPX 7440P at 4", SPX_CHANNEL)
        await _process_one(analyst, msg)
        sig = signal_queue.get_nowait()
        assert sig.direction == "PUT"
        assert sig.strike == 7440.0
        assert sig.signal_price == 4.0

    async def test_duplicate_signal_suppressed(
        self, analyst: VinodSPXAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        msg = _msg("**SPX :** Bought SPX 7550C at 3.50", SPX_CHANNEL)
        await _process_one(analyst, msg)
        assert not signal_queue.empty()
        signal_queue.get_nowait()  # consume first

        # Same analyst, same symbol+strike+direction → dedup key matches
        await _process_one(analyst, msg)
        assert signal_queue.empty(), "Duplicate signal was not suppressed"

    async def test_kill_switch_blocks_emission(
        self, analyst: VinodSPXAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        set_blocked("e2e test", KILL_SWITCH)
        try:
            msg = _msg("**SPX :** Bought SPX 7600C at 2.50", SPX_CHANNEL)
            await _process_one(analyst, msg)
            assert signal_queue.empty(), "Signal emitted despite active kill switch"
        finally:
            set_healthy(KILL_SWITCH)

    async def test_premium_cap_rejects_expensive_signal(
        self, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        # $5.00 premium = $500/contract, max_premium_usd=400
        analyst = VinodSPXAnalyst(
            signal_queue=signal_queue, channel_id=SPX_CHANNEL, max_premium_usd=400.0
        )
        analyst._running = True
        msg = _msg("**SPX :** Bought SPX 7550C at 5.00", SPX_CHANNEL)
        await _process_one(analyst, msg)
        assert signal_queue.empty(), "$500 contract was not rejected (max=$400)"

    async def test_es_futures_not_traded(
        self, analyst: VinodSPXAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        msg = _msg("**SPX :** ES Long 7385 Stoploss 7375", SPX_CHANNEL)
        await _process_one(analyst, msg)
        assert signal_queue.empty(), "ES futures message produced a signal"

    async def test_butterfly_not_traded(
        self, analyst: VinodSPXAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        msg = _msg("**SPX :** Bought SPX 7440/7450/7460C FLY at 1.40 Lotto", SPX_CHANNEL)
        await _process_one(analyst, msg)
        assert signal_queue.empty(), "Butterfly produced a signal"

    async def test_execution_limit_price_is_buffered(
        self, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        """Limit price = signal_price × (1 + execution_buffer_pct)."""
        analyst = VinodSPXAnalyst(
            signal_queue=signal_queue,
            channel_id=SPX_CHANNEL,
            execution_buffer_pct=0.20,
        )
        analyst._running = True
        msg = _msg("**SPX :** Bought SPX 7550C at 3.50", SPX_CHANNEL)
        await _process_one(analyst, msg)
        sig = signal_queue.get_nowait()
        # The signal_price is Vinod's price; execution uses 3.50 × 1.20 = 4.20
        assert sig.signal_price == 3.50
        assert sig.source_metadata["execution_buffer_pct"] == 0.20


# ─── VinodOtherAnalyst ────────────────────────────────────────────────────────

class TestVinodOtherE2E:
    @pytest.fixture
    def signal_queue(self) -> "asyncio.Queue[TradeSignal]":
        return asyncio.Queue()

    @pytest.fixture
    def analyst(self, signal_queue: "asyncio.Queue[TradeSignal]") -> VinodOtherAnalyst:
        a = VinodOtherAnalyst(signal_queue=signal_queue, channel_id=OTHER_CHANNEL)
        a._running = True
        return a

    async def test_other_buy_partial_sell_exit(
        self, analyst: VinodOtherAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        msg = _msg("**OTHER :** Bought TSLA 430C at 1.70 Expiring today", OTHER_CHANNEL)
        await _process_one(analyst, msg)
        sig = signal_queue.get_nowait()
        assert sig.symbol == "TSLA"
        assert sig.direction == "CALL"
        assert sig.exit_rules.strategy == "PARTIAL_SELL_PCT"
        assert sig.exit_rules.partial_sell_pct == 0.70
        assert sig.exit_rules.source_channel_id == OTHER_CHANNEL

    async def test_spy_trades_in_other_channel(
        self, analyst: VinodOtherAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        """SPY is valid in Other channel — must NOT be excluded."""
        msg = _msg("**OTHER :** Bought SPY 735P at 1.10 Exp: 06/15/2026", OTHER_CHANNEL)
        await _process_one(analyst, msg)
        sig = signal_queue.get_nowait()
        assert sig.symbol == "SPY"
        assert sig.direction == "PUT"

    async def test_spx_in_other_channel_ignored(
        self, analyst: VinodOtherAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        """SPX trades in Other channel belong to the SPX analyst."""
        msg = _msg("**OTHER :** Bought SPX 7550C at 3.50 Exp: 06/12/2026", OTHER_CHANNEL)
        await _process_one(analyst, msg)
        assert signal_queue.empty(), "SPX trade in Other channel should not produce signal"

    async def test_kill_switch_blocks_other(
        self, analyst: VinodOtherAnalyst, signal_queue: "asyncio.Queue[TradeSignal]"
    ) -> None:
        set_blocked("e2e test", KILL_SWITCH)
        try:
            msg = _msg("**OTHER :** Bought NVDA 220C at 1.30 Exp: 06/12/2026", OTHER_CHANNEL)
            await _process_one(analyst, msg)
            assert signal_queue.empty(), "Signal emitted despite active kill switch"
        finally:
            set_healthy(KILL_SWITCH)

"""
tests/integration/test_full_pipeline.py

M1.6 End-to-end integration test:
Discord message -> VinodSPXAnalyst -> signal_queue ->
MasterAnalyst (mocked LLM) -> gateway_queue ->
RHGateway (paper mode) -> OrderRecord

No live connections required.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, date

from analysts.discord.vinod import VinodSPXAnalyst
from master.master_analyst import MasterAnalyst
from gateway.rh_gateway import RHGateway
from core.base_analyst import WakeEvent
from core.schemas import TradeSignal, OptionContract


@pytest.mark.asyncio
async def test_full_pipeline_spx_call(tmp_path):
    """Discord message -> Vinod -> Master -> Gateway -> paper order"""
    signal_queue: asyncio.Queue[TradeSignal] = asyncio.Queue()
    gateway_queue: asyncio.Queue[TradeSignal] = asyncio.Queue()

    # 1. Vinod parses a Discord message and puts it on signal_queue
    analyst = VinodSPXAnalyst(signal_queue=signal_queue, channel_id="1495516216645783562")
    analyst._running = True

    msg = {
        "message_id": "e2e-001",
        "channel_id": "1495516216645783562",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "author_id": "9001",
        "author_name": "INFRA TRADE ALERT",
        "author_global_name": "INFRA TRADE ALERT",
        "is_bot": True,
        "content_raw": "**SPX :** Bought SPX 7550C at 3.50",
        "content": "**SPX :** Bought SPX 7550C at 3.50",
        "embeds": [],
    }
    event = WakeEvent(trigger="DISCORD_MESSAGE", raw=msg, channel_id=msg["channel_id"])
    await analyst.wake(event)
    assert not signal_queue.empty(), "VinodSPXAnalyst must put a signal on the queue"

    # 2. MasterAnalyst processes it (LLM call mocked)
    with patch("master.master_analyst.MasterAnalyst._ask_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = (True, "SPX call looks good, momentum confirmed")
        master = MasterAnalyst(signal_queue=signal_queue, gateway_queue=gateway_queue)
        signal = signal_queue.get_nowait()
        await master._process(signal)

    assert not gateway_queue.empty(), "MasterAnalyst must forward approved signal to gateway_queue"
    approved: TradeSignal = gateway_queue.get_nowait()
    # MasterAnalyst forwards the original PENDING signal (frozen model) to the gateway_queue
    # when Claude approves it. The gateway then executes it.
    assert approved.symbol == "SPX"
    assert approved.direction == "CALL"

    # 3. RH Gateway executes the approved signal in paper mode
    gateway = RHGateway(paper_mode=True)
    mock_contract = OptionContract(
        symbol="SPX",
        direction="CALL",
        strike=7550.0,
        expiry=date.today(),
        bid_per_share=3.40,
        ask_per_share=3.60,
        mark_per_share=3.50,
        open_interest=1000,
        volume=500,
    )
    with patch.object(gateway, "get_quote", new_callable=AsyncMock) as mock_quote:
        mock_quote.return_value = mock_contract
        order = await gateway.execute_signal(approved)

    assert order is not None, "RHGateway must return an OrderRecord in paper mode"
    assert order.symbol == "SPX"
    assert order.paper_mode is True
    print(
        f"Full pipeline test PASSED: signal_id={approved.signal_id}, order_id={order.order_id}"
    )

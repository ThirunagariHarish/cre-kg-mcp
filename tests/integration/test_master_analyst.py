"""
tests/integration/test_master_analyst.py — Integration tests for MasterAnalyst.

Tests:
  1. test_approved_signal_reaches_gateway    — happy path: LLM approves, signal lands on gateway_queue
  2. test_duplicate_suppressed               — same signal twice within 5 min, only one passes
  3. test_kill_switch_blocks                 — is_blocked() True → signal rejected, never forwarded
  4. test_rejection_logged                   — LLM rejects → journal called with SIGNAL_REJECTED
  5. test_expired_dedup_allowed              — signal, wait past 5 min (mocked time), same again → passes

All tests use asyncio_mode = "auto" (configured in pyproject.toml).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.schemas import Evidence, ExitRules, TradeSignal
from master.master_analyst import MasterAnalyst, _DEDUP_WINDOW_SECONDS


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_signal(
    analyst_id: str = "test_analyst",
    symbol: str = "SPX",
    direction: str = "CALL",
    strike: float = 5000.0,
    expiry: date | None = None,
) -> TradeSignal:
    """Build a minimal valid TradeSignal for testing."""
    if expiry is None:
        expiry = date(2026, 6, 20)

    evidence = [
        Evidence(
            indicator="RSI",
            value=72,
            interpretation="Overbought — but momentum strong",
            weight=0.7,
            bullish=True,
        ),
        Evidence(
            indicator="MACD",
            value="bullish_cross",
            interpretation="MACD crossed above signal line",
            weight=0.8,
            bullish=True,
        ),
    ]
    exit_rules = ExitRules(
        strategy="MANUAL",
    )
    return TradeSignal(
        analyst_id=analyst_id,
        source_layer="DISCORD",
        timestamp=datetime.now(tz=timezone.utc),
        symbol=symbol,
        direction=direction,
        strike=strike,
        expiry=expiry,
        signal_price=3.50,
        evidence=evidence,
        risk_level="MEDIUM",
        confidence=0.75,
        exit_rules=exit_rules,
    )


def _make_master(paper_mode: bool = True) -> tuple[MasterAnalyst, asyncio.Queue, asyncio.Queue]:
    """Create a MasterAnalyst with fresh queues."""
    signal_q: asyncio.Queue[TradeSignal] = asyncio.Queue()
    gateway_q: asyncio.Queue[TradeSignal] = asyncio.Queue()
    master = MasterAnalyst(signal_q, gateway_q, paper_mode=paper_mode)
    return master, signal_q, gateway_q


# ─── Tests ───────────────────────────────────────────────────────────────────

async def test_approved_signal_reaches_gateway():
    """
    When _ask_claude returns (True, 'looks good'), the signal must end up
    on gateway_queue and NOT be rejected.
    """
    master, signal_q, gateway_q = _make_master()
    signal = _make_signal()

    with (
        patch("master.master_analyst.is_blocked", return_value=False),
        patch.object(master, "_ask_claude", new=AsyncMock(return_value=(True, "looks good"))),
        patch("master.master_analyst.journal") as mock_journal,
    ):
        await master._process(signal)

    assert not gateway_q.empty(), "Signal should have been forwarded to gateway_queue"
    forwarded = await gateway_q.get()
    assert forwarded.signal_id == signal.signal_id

    # Approved journal entry should be present
    journal_calls = [call.args[0] for call in mock_journal.call_args_list]
    from core.logging import TradeEvent
    assert TradeEvent.SIGNAL_APPROVED in journal_calls


async def test_duplicate_suppressed():
    """
    Sending the same signal twice within the dedup window should result in
    only one signal reaching gateway_queue. The second is dropped.
    """
    master, signal_q, gateway_q = _make_master()
    signal = _make_signal()

    with (
        patch("master.master_analyst.is_blocked", return_value=False),
        patch.object(master, "_ask_claude", new=AsyncMock(return_value=(True, "good"))),
        patch("master.master_analyst.journal"),
    ):
        # Process the same signal twice — second should be deduplicated
        await master._process(signal)
        await master._process(signal)

    assert gateway_q.qsize() == 1, (
        f"Expected exactly 1 signal on gateway_queue, got {gateway_q.qsize()}"
    )
    assert master._duplicate_count == 1


async def test_kill_switch_blocks():
    """
    When is_blocked() returns True, the signal must be rejected immediately
    (no LLM call) and must NOT appear on gateway_queue.
    """
    master, signal_q, gateway_q = _make_master()
    signal = _make_signal()

    ask_claude_mock = AsyncMock(return_value=(True, "would approve"))

    with (
        patch("master.master_analyst.is_blocked", return_value=True),
        patch.object(master, "_ask_claude", new=ask_claude_mock),
        patch("master.master_analyst.journal") as mock_journal,
    ):
        await master._process(signal)

    # LLM should NOT have been called
    ask_claude_mock.assert_not_called()

    # Signal must NOT reach gateway
    assert gateway_q.empty(), "Kill-switch-blocked signal must not reach gateway_queue"

    # Rejection should be journaled
    from core.logging import TradeEvent
    journal_events = [call.args[0] for call in mock_journal.call_args_list]
    assert TradeEvent.SIGNAL_REJECTED in journal_events


async def test_rejection_logged():
    """
    When _ask_claude returns (False, 'too expensive'), journal must be called
    with SIGNAL_REJECTED and the reason must appear in the extra payload.
    """
    master, signal_q, gateway_q = _make_master()
    signal = _make_signal()

    with (
        patch("master.master_analyst.is_blocked", return_value=False),
        patch.object(master, "_ask_claude", new=AsyncMock(return_value=(False, "too expensive"))),
        patch("master.master_analyst.journal") as mock_journal,
    ):
        await master._process(signal)

    # Signal must NOT reach gateway
    assert gateway_q.empty(), "Rejected signal must not reach gateway_queue"
    assert master._rejected_count == 1

    # Find the SIGNAL_REJECTED journal call and verify the reason
    from core.logging import TradeEvent
    rejection_calls = [
        call for call in mock_journal.call_args_list
        if call.args[0] == TradeEvent.SIGNAL_REJECTED
    ]
    assert len(rejection_calls) >= 1, "Expected at least one SIGNAL_REJECTED journal entry"

    # Check the extra payload contains the reason
    extra = rejection_calls[0].kwargs.get("extra", {})
    assert extra.get("rejection_reason") == "too expensive", (
        f"Expected rejection_reason='too expensive', got: {extra}"
    )


async def test_expired_dedup_allowed():
    """
    If the same signal is sent, dedup window expires (mocked), then the same
    signal is sent again — the second one MUST pass through.
    """
    master, signal_q, gateway_q = _make_master()
    signal = _make_signal()

    with (
        patch("master.master_analyst.is_blocked", return_value=False),
        patch.object(master, "_ask_claude", new=AsyncMock(return_value=(True, "good"))),
        patch("master.master_analyst.journal"),
    ):
        # First signal — should pass through and be recorded in _seen
        await master._process(signal)

        # Manually age the dedup entry past the window
        key = master._dedup_key(signal)
        expired_time = datetime.now(tz=timezone.utc) - timedelta(seconds=_DEDUP_WINDOW_SECONDS + 1)
        master._seen[key] = expired_time

        # Second signal — dedup should have expired, so it passes through
        await master._process(signal)

    assert gateway_q.qsize() == 2, (
        f"Expected 2 signals (first + post-expiry), got {gateway_q.qsize()}"
    )
    assert master._duplicate_count == 0


async def test_cancelled_error_propagates():
    """
    CancelledError must propagate cleanly out of run() without being swallowed.
    """
    master, signal_q, gateway_q = _make_master()

    async def run_and_cancel():
        task = asyncio.create_task(master.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return True  # expected
        return False

    result = await run_and_cancel()
    assert result, "CancelledError should have propagated from run()"

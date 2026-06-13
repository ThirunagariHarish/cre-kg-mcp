"""
tests/unit/test_memory_journal.py — Unit tests for MemoryJournal.

All tests use an in-memory SQLite DB (:memory:) via a patched db_path.
Uses pytest-asyncio with asyncio_mode = "auto" (inherited from pyproject.toml).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from core.schemas import ExitRules, PositionRecord, TradeSignal, Evidence
from master.memory_journal import MemoryJournal, _compute_pattern_type


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
async def journal() -> MemoryJournal:
    """Fresh in-memory journal, tables already created."""
    jnl = MemoryJournal(db_path=":memory:")
    await jnl.initialize()
    return jnl


def _make_position(
    analyst_id: str = "vinod_spx",
    symbol: str = "SPX",
    direction: str = "CALL",
    avg_cost_per_share: float = 2.00,
    qty: int = 1,
) -> PositionRecord:
    return PositionRecord(
        position_id=str(uuid.uuid4()),
        order_id=str(uuid.uuid4()),
        signal_id=str(uuid.uuid4()),
        analyst_id=analyst_id,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        strike=4500.0,
        expiry=date.today(),
        qty=qty,
        avg_cost_per_share=avg_cost_per_share,
        avg_cost_per_contract=avg_cost_per_share * 100,
        opened_at=datetime.utcnow(),
        exit_rules=ExitRules(
            strategy="FIRST_SELL_FROM_SOURCE",
            source_channel_id="123456",
        ),
    )


def _make_signal(
    analyst_id: str = "vinod_spx",
    symbol: str = "SPX",
    direction: str = "CALL",
    expiry: date | None = None,
) -> TradeSignal:
    if expiry is None:
        expiry = date.today()
    return TradeSignal(
        signal_id=str(uuid.uuid4()),
        analyst_id=analyst_id,
        source_layer="DISCORD",
        timestamp=datetime.utcnow(),
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        strike=4500.0,
        expiry=expiry,
        signal_price=2.00,
        evidence=[
            Evidence(
                indicator="RSI",
                value=65,
                interpretation="Overbought but trending",
                weight=0.7,
                bullish=True,
            )
        ],
        risk_level="MEDIUM",
        confidence=0.75,
        exit_rules=ExitRules(
            strategy="FIRST_SELL_FROM_SOURCE",
            source_channel_id="123456",
        ),
    )


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────


async def test_record_close_writes_to_db(journal: MemoryJournal) -> None:
    """record_close inserts exactly one row into the trades table."""
    import aiosqlite as _aiosqlite

    position = _make_position()
    await journal.record_close(position, exit_price_per_share=3.00, exit_reason="TARGET_HIT")

    # Use the journal's own connection context so we query the same :memory: DB.
    async with journal._conn() as db:
        db.row_factory = _aiosqlite.Row
        async with db.execute(
            "SELECT * FROM trades WHERE trade_id = ?", (position.position_id,)
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None, "Expected a row in trades table after record_close"
    assert row["outcome"] == "WIN"  # (3.00 - 2.00) / 2.00 = 50% gain
    assert row["exit_reason"] == "TARGET_HIT"
    assert row["analyst_id"] == position.analyst_id
    assert row["symbol"] == position.symbol


async def test_win_rate_calculation(journal: MemoryJournal) -> None:
    """3 wins + 2 losses → win_rate == 0.60."""
    analyst_id = "test_analyst"

    # 3 wins — exit at 3.00, entry 2.00 → +50% > WIN threshold
    for _ in range(3):
        pos = _make_position(analyst_id=analyst_id)
        await journal.record_close(pos, exit_price_per_share=3.00, exit_reason="WIN_TEST")

    # 2 losses — exit at 1.00, entry 2.00 → -50% < LOSS threshold
    for _ in range(2):
        pos = _make_position(analyst_id=analyst_id)
        await journal.record_close(pos, exit_price_per_share=1.00, exit_reason="LOSS_TEST")

    win_rate = await journal.get_analyst_win_rate(analyst_id, min_trades=5)
    assert win_rate is not None
    assert abs(win_rate - 0.60) < 1e-9, f"Expected 0.60, got {win_rate}"


async def test_should_reject_below_40pct(journal: MemoryJournal) -> None:
    """10+ trades all losses → should_reject_pattern returns True."""
    analyst_id = "bad_analyst"
    signal = _make_signal(analyst_id=analyst_id)
    pattern = _compute_pattern_type(signal)

    for _ in range(10):
        pos = _make_position(analyst_id=analyst_id)
        await journal.record_close(
            pos,
            exit_price_per_share=0.50,  # -75% → LOSS
            exit_reason="STOP_LOSS",
            signal=signal,
        )

    should_reject = await journal.should_reject_pattern(analyst_id, pattern)
    assert should_reject is True


async def test_insufficient_data_returns_none(journal: MemoryJournal) -> None:
    """< 5 decided trades → get_analyst_win_rate returns None."""
    analyst_id = "new_analyst"

    # Only 4 trades
    for _ in range(4):
        pos = _make_position(analyst_id=analyst_id)
        await journal.record_close(pos, exit_price_per_share=3.00, exit_reason="WIN_TEST")

    result = await journal.get_analyst_win_rate(analyst_id, min_trades=5)
    assert result is None, f"Expected None for < 5 trades, got {result}"


async def test_pattern_type_0dte(journal: MemoryJournal) -> None:
    """expiry == today → pattern_type includes '0DTE'."""
    signal = _make_signal(expiry=date.today())
    pattern = _compute_pattern_type(signal)
    assert "0DTE" in pattern, f"Expected '0DTE' in pattern_type, got '{pattern}'"


async def test_pattern_type_swing(journal: MemoryJournal) -> None:
    """expiry > 3 days from today → pattern_type includes 'SWING'."""
    expiry = date.today() + timedelta(days=10)
    signal = _make_signal(expiry=expiry)
    pattern = _compute_pattern_type(signal)
    assert "SWING" in pattern, f"Expected 'SWING' in pattern_type, got '{pattern}'"


async def test_pattern_type_weekly(journal: MemoryJournal) -> None:
    """1 <= days_to_expiry <= 3 → pattern_type includes 'WEEKLY'."""
    expiry = date.today() + timedelta(days=2)
    signal = _make_signal(expiry=expiry)
    pattern = _compute_pattern_type(signal)
    assert "WEEKLY" in pattern, f"Expected 'WEEKLY' in pattern_type, got '{pattern}'"


async def test_get_recent_trades_filters_by_days(journal: MemoryJournal) -> None:
    """get_recent_trades returns only trades within the requested window."""
    analyst_id = "recent_analyst"
    pos = _make_position(analyst_id=analyst_id)
    await journal.record_close(pos, exit_price_per_share=3.00, exit_reason="TARGET")

    results = await journal.get_recent_trades(analyst_id, days=7)
    assert len(results) == 1
    assert results[0]["analyst_id"] == analyst_id


async def test_get_pattern_win_rate_returns_correct_fields(journal: MemoryJournal) -> None:
    """get_pattern_win_rate returns a dict with win_rate, total_trades, avg_pnl_pct."""
    analyst_id = "pattern_analyst"
    signal = _make_signal(analyst_id=analyst_id)
    pattern = _compute_pattern_type(signal)

    # 1 win
    pos = _make_position(analyst_id=analyst_id)
    await journal.record_close(pos, exit_price_per_share=3.00, exit_reason="WIN", signal=signal)
    # 1 loss
    pos2 = _make_position(analyst_id=analyst_id)
    await journal.record_close(pos2, exit_price_per_share=1.00, exit_reason="LOSS", signal=signal)

    result = await journal.get_pattern_win_rate(analyst_id, pattern)
    assert "win_rate" in result
    assert "total_trades" in result
    assert "avg_pnl_pct" in result
    assert result["total_trades"] == 2
    assert abs(result["win_rate"] - 0.5) < 1e-9


async def test_should_not_reject_with_insufficient_trades(journal: MemoryJournal) -> None:
    """< 10 trades → should_reject_pattern returns False even if all losses."""
    analyst_id = "new_bad_analyst"
    signal = _make_signal(analyst_id=analyst_id)
    pattern = _compute_pattern_type(signal)

    for _ in range(5):
        pos = _make_position(analyst_id=analyst_id)
        await journal.record_close(pos, exit_price_per_share=0.50, exit_reason="LOSS", signal=signal)

    should_reject = await journal.should_reject_pattern(analyst_id, pattern)
    assert should_reject is False

"""
tests/unit/test_greeks_monitor.py — Unit tests for core/greeks_monitor.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.greeks_monitor import GreeksMonitor, PositionGreeks
from core.schemas import OptionContract


# ─────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────

@dataclass
class _FakePosition:
    """Minimal stand-in for PositionRecord."""
    position_id: str
    symbol: str
    direction: str
    strike: float
    expiry: date
    avg_cost_per_share: float
    account_id: str = "primary"


def _make_pos(
    avg_cost: float = 2.0,
    expiry: date | None = None,
    symbol: str = "SPY",
    direction: str = "CALL",
    strike: float = 450.0,
) -> _FakePosition:
    return _FakePosition(
        position_id="pos-001",
        symbol=symbol,
        direction=direction,
        strike=strike,
        expiry=expiry or date(2025, 12, 19),
        avg_cost_per_share=avg_cost,
    )


def _make_contract(bid: float = 1.0, ask: float = 1.4, oi: int = 500) -> OptionContract:
    return OptionContract(
        symbol="SPY",
        direction="CALL",
        strike=450.0,
        expiry=date(2025, 12, 19),
        bid_per_share=bid,
        ask_per_share=ask,
        mark_per_share=(bid + ask) / 2,
        open_interest=oi,
        volume=1000,
    )


def _monitor_with_contract(contract: OptionContract | None) -> GreeksMonitor:
    mock_client = MagicMock()
    mock_client.get_option_quote = AsyncMock(return_value=contract)
    return GreeksMonitor(polygon_client=mock_client)


# ─────────────────────────────────────────────────────────
# test_pnl_calculation
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pnl_calculation() -> None:
    """avg_cost=2.0, current mark=3.0 -> pnl_pct=0.50, pnl_per_contract=100."""
    # mark = (1.0 + 5.0) / 2 = 3.0
    contract = _make_contract(bid=1.0, ask=5.0)
    monitor = _monitor_with_contract(contract)
    pos = _make_pos(avg_cost=2.0)

    with patch.object(monitor, "_write_greeks_file"):
        result = await monitor._refresh_position(pos)

    assert result.current_price == pytest.approx(3.0)
    assert result.entry_price == pytest.approx(2.0)
    assert result.pnl_per_share == pytest.approx(1.0)
    assert result.pnl_pct == pytest.approx(0.50)
    assert result.pnl_per_contract == pytest.approx(100.0)


# ─────────────────────────────────────────────────────────
# test_wide_spread_alert
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wide_spread_alert() -> None:
    """bid=0.5, ask=2.0 -> spread > 15% of mid -> alert='WIDE_SPREAD'."""
    # mid = (0.5 + 2.0) / 2 = 1.25
    # spread_pct = (2.0 - 0.5) / 1.25 = 1.2  > 0.15
    contract = _make_contract(bid=0.5, ask=2.0, oi=200)  # oi > 100 so LOW_OI won't fire first
    monitor = _monitor_with_contract(contract)
    pos = _make_pos(avg_cost=1.0, expiry=date(2025, 12, 19))

    result = await monitor._refresh_position(pos)

    assert result.spread_pct > GreeksMonitor.SPREAD_ALERT_PCT
    assert result.alert == "WIDE_SPREAD"


# ─────────────────────────────────────────────────────────
# test_near_expiry_alert
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_near_expiry_alert() -> None:
    """dte=0 and hour>=19 (UTC) -> alert='NEAR_EXPIRY'."""
    today = datetime.now(timezone.utc).date()
    contract = _make_contract(bid=1.0, ask=1.2, oi=200)
    monitor = _monitor_with_contract(contract)
    pos = _make_pos(avg_cost=1.0, expiry=today)

    # Freeze UTC time to 19:30 (past 3 PM ET)
    frozen_now = datetime(today.year, today.month, today.day, 19, 30, 0, tzinfo=timezone.utc)
    with patch("core.greeks_monitor.datetime") as mock_dt:
        mock_dt.now.return_value = frozen_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = await monitor._refresh_position(pos)

    assert result.days_to_expiry == 0
    assert result.alert == "NEAR_EXPIRY"


@pytest.mark.asyncio
async def test_no_near_expiry_alert_before_close() -> None:
    """dte=0 but hour<19 -> should NOT trigger NEAR_EXPIRY."""
    today = datetime.now(timezone.utc).date()
    contract = _make_contract(bid=1.0, ask=1.2, oi=200)
    monitor = _monitor_with_contract(contract)
    pos = _make_pos(avg_cost=1.0, expiry=today)

    frozen_now = datetime(today.year, today.month, today.day, 15, 0, 0, tzinfo=timezone.utc)
    with patch("core.greeks_monitor.datetime") as mock_dt:
        mock_dt.now.return_value = frozen_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = await monitor._refresh_position(pos)

    assert result.days_to_expiry == 0
    assert result.alert != "NEAR_EXPIRY"


# ─────────────────────────────────────────────────────────
# test_fallback_no_crash
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_no_crash() -> None:
    """When Polygon returns None, entry price is used and no exception raised."""
    monitor = _monitor_with_contract(None)
    pos = _make_pos(avg_cost=3.50)

    result = await monitor._refresh_position(pos)

    assert result.current_price == pytest.approx(3.50)
    assert result.pnl_per_share == pytest.approx(0.0)
    assert result.pnl_pct == pytest.approx(0.0)
    assert result.spread_pct == pytest.approx(0.0)
    assert result.volume == 0
    assert result.open_interest == 0
    assert result.delta is None


# ─────────────────────────────────────────────────────────
# test_refresh_all — concurrent gather + file write
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_all_aggregates_results() -> None:
    """refresh_all should return one PositionGreeks per valid position."""
    contract = _make_contract()
    monitor = _monitor_with_contract(contract)
    positions = [_make_pos(avg_cost=2.0), _make_pos(avg_cost=3.0)]

    with patch.object(monitor, "_write_greeks_file"):
        results = await monitor.refresh_all(positions)

    assert len(results) == 2
    assert all(isinstance(r, PositionGreeks) for r in results)


@pytest.mark.asyncio
async def test_refresh_all_skips_exceptions() -> None:
    """Exceptions from individual positions don't crash refresh_all."""
    mock_client = MagicMock()
    mock_client.get_option_quote = AsyncMock(side_effect=RuntimeError("network error"))
    monitor = GreeksMonitor(polygon_client=mock_client)

    positions = [_make_pos()]

    with patch.object(monitor, "_write_greeks_file"):
        results = await monitor.refresh_all(positions)

    # All positions failed — list should be empty (no crash)
    assert results == []


# ─────────────────────────────────────────────────────────
# test_low_oi_alert
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_low_oi_alert() -> None:
    """open_interest < 100 and > 0 -> alert='LOW_OI'."""
    contract = _make_contract(bid=1.0, ask=1.1, oi=50)  # spread < 15% so WIDE_SPREAD won't fire
    monitor = _monitor_with_contract(contract)
    pos = _make_pos(avg_cost=1.0, expiry=date(2025, 12, 19))

    result = await monitor._refresh_position(pos)

    assert result.open_interest == 50
    assert result.alert == "LOW_OI"


# ─────────────────────────────────────────────────────────
# test_no_alert_when_healthy
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_alert_when_healthy() -> None:
    """Healthy position: no alert."""
    contract = _make_contract(bid=1.0, ask=1.05, oi=500)  # tiny spread, good OI
    monitor = _monitor_with_contract(contract)
    pos = _make_pos(avg_cost=1.0, expiry=date(2025, 12, 19))

    result = await monitor._refresh_position(pos)

    assert result.alert is None

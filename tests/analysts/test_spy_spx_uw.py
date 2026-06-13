"""
Tests for analysts/unusual_whales/spy_spx.py (M3.3 — SPY/SPX UW Analyst).

All tests are pure unit tests — no asyncio event loop, no network, no file I/O.
The market data dict is passed directly to the pure helper functions.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from analysts.unusual_whales.spy_spx import (
    SPYSPXUWAnalyst,
    atm_strike,
    build_evidence_from_market_data,
    bullish_score_from_evidence,
    nearest_friday,
)
from core.schemas import ExitRules, TradeSignal


# ─── Fixtures / helpers ───────────────────────────────────────────────────────

def _bullish_market_data() -> dict:
    """Market snapshot that strongly favours CALL."""
    return {
        "call_put_ratio": 1.5,        # > 1.2 bullish
        "gex": 5_000_000,             # positive → bullish
        "spy_call_volume": 600_000,   # 3× avg of 200k → unusual bullish
        "spy_call_volume_avg_20d": 200_000,
        "vix": 15.0,                  # < 20 → low fear → bullish
        "spy_price": 580.00,
        "spy_vwap": 575.00,           # price above VWAP → bullish
    }


def _bearish_market_data() -> dict:
    """Market snapshot that strongly favours PUT."""
    return {
        "call_put_ratio": 0.6,        # < 0.8 bearish
        "gex": -8_000_000,            # negative → bearish
        "spy_call_volume": 50_000,    # only 0.25× avg — no unusual call volume → NOT bullish
        "spy_call_volume_avg_20d": 200_000,
        "vix": 28.0,                  # > 20 → elevated fear → bearish
        "spy_price": 570.00,
        "spy_vwap": 578.00,           # price below VWAP → bearish
    }


def _uncertain_market_data() -> dict:
    """Market snapshot with mixed signals — no decisive direction."""
    return {
        "call_put_ratio": 1.0,        # neutral → treated as bullish (mildly)
        "gex": 1_000,                 # barely positive → bullish
        "spy_call_volume": 250_000,   # 1.25× avg — below 3× threshold → NOT bullish (vol filter)
        "spy_call_volume_avg_20d": 200_000,
        "vix": 21.0,                  # slightly above 20 → bearish
        "spy_price": 580.00,
        "spy_vwap": 580.00,           # exactly at VWAP → bullish (edge case)
    }


# ─── Evidence builder tests ───────────────────────────────────────────────────

class TestBuildEvidenceFromMarketData:
    def test_bullish_data_returns_five_items(self) -> None:
        ev = build_evidence_from_market_data(_bullish_market_data())
        assert len(ev) == 5

    def test_bearish_data_returns_five_items(self) -> None:
        ev = build_evidence_from_market_data(_bearish_market_data())
        assert len(ev) == 5

    def test_weights_sum_to_one(self) -> None:
        ev = build_evidence_from_market_data(_bullish_market_data())
        total = sum(e.weight for e in ev)
        assert abs(total - 1.0) < 1e-9

    def test_bullish_data_all_bullish(self) -> None:
        ev = build_evidence_from_market_data(_bullish_market_data())
        assert all(e.bullish for e in ev)

    def test_bearish_data_all_bearish(self) -> None:
        ev = build_evidence_from_market_data(_bearish_market_data())
        assert all(not e.bullish for e in ev)

    def test_indicators_present(self) -> None:
        ev = build_evidence_from_market_data(_bullish_market_data())
        indicators = {e.indicator for e in ev}
        assert "call_put_ratio" in indicators
        assert "gex" in indicators
        assert "uw_call_volume" in indicators
        assert "vix" in indicators
        assert "spy_vs_vwap" in indicators

    def test_call_put_ratio_low_is_bearish(self) -> None:
        data = _bullish_market_data()
        data["call_put_ratio"] = 0.5  # well below 0.8
        ev = build_evidence_from_market_data(data)
        cp_ev = next(e for e in ev if e.indicator == "call_put_ratio")
        assert not cp_ev.bullish

    def test_vix_above_20_is_bearish(self) -> None:
        data = _bullish_market_data()
        data["vix"] = 25.0
        ev = build_evidence_from_market_data(data)
        vix_ev = next(e for e in ev if e.indicator == "vix")
        assert not vix_ev.bullish

    def test_vwap_guard_against_zero(self) -> None:
        data = _bullish_market_data()
        data["spy_vwap"] = 0.0  # should not crash
        ev = build_evidence_from_market_data(data)
        assert len(ev) == 5

    def test_volume_below_threshold_is_bearish(self) -> None:
        data = _bullish_market_data()
        data["spy_call_volume"] = 100_000  # only 0.5× avg
        data["spy_call_volume_avg_20d"] = 200_000
        ev = build_evidence_from_market_data(data)
        vol_ev = next(e for e in ev if e.indicator == "uw_call_volume")
        assert not vol_ev.bullish


# ─── Score tests ──────────────────────────────────────────────────────────────

class TestBullishScore:
    def test_all_bullish_score_is_one(self) -> None:
        ev = build_evidence_from_market_data(_bullish_market_data())
        assert bullish_score_from_evidence(ev) == pytest.approx(1.0)

    def test_all_bearish_score_is_zero(self) -> None:
        ev = build_evidence_from_market_data(_bearish_market_data())
        assert bullish_score_from_evidence(ev) == pytest.approx(0.0)

    def test_score_is_weighted(self) -> None:
        from analysts.unusual_whales.spy_spx import build_evidence_from_market_data as _bev
        # Only call_put_ratio (0.25) and gex (0.20) bullish; rest bearish
        data = {
            "call_put_ratio": 1.5,    # bullish w=0.25
            "gex": 5_000_000,         # bullish w=0.20
            "spy_call_volume": 100,   # NOT bullish w=0.30
            "spy_call_volume_avg_20d": 200_000,
            "vix": 25.0,              # NOT bullish w=0.15
            "spy_price": 570.0,
            "spy_vwap": 580.0,        # NOT bullish w=0.10
        }
        ev = _bev(data)
        score = bullish_score_from_evidence(ev)
        # bullish weight = 0.25 + 0.20 = 0.45; total = 1.0
        assert score == pytest.approx(0.45)


# ─── Contract selection (direction decision) tests ────────────────────────────

class TestSPYSPXUWAnalystSignals:
    """Integration-style tests on the analyst using mocked _fetch_market_data."""

    def _make_analyst(self) -> tuple[SPYSPXUWAnalyst, "asyncio.Queue[TradeSignal]"]:
        q: asyncio.Queue[TradeSignal] = asyncio.Queue()
        analyst = SPYSPXUWAnalyst(signal_queue=q)
        return analyst, q

    @pytest.mark.asyncio
    async def test_bullish_signal_emits_call(self) -> None:
        """Strong bullish market data → CALL signal on SPY."""
        analyst, q = self._make_analyst()

        analyst._fetch_market_data = AsyncMock(return_value=_bullish_market_data())

        # Patch kill switch to healthy
        with patch("core.kill_switch.is_blocked", return_value=False):
            with patch("core.logging.append_jsonl"):
                wake_event = MagicMock()
                wake_event.trigger = "SCHEDULE"
                wake_event.raw = None
                raw = await analyst.gather_data(wake_event)
                evidence = await analyst.build_evidence(raw)
                contract = await analyst.select_contract(evidence, raw)

        assert contract is not None
        assert contract.direction == "CALL"
        assert contract.symbol == "SPY"

    @pytest.mark.asyncio
    async def test_bearish_signal_emits_put(self) -> None:
        """Strong bearish market data → PUT signal on SPY."""
        analyst, q = self._make_analyst()
        analyst._fetch_market_data = AsyncMock(return_value=_bearish_market_data())

        with patch("core.kill_switch.is_blocked", return_value=False):
            with patch("core.logging.append_jsonl"):
                wake_event = MagicMock()
                wake_event.trigger = "SCHEDULE"
                wake_event.raw = None
                raw = await analyst.gather_data(wake_event)
                evidence = await analyst.build_evidence(raw)
                contract = await analyst.select_contract(evidence, raw)

        assert contract is not None
        assert contract.direction == "PUT"
        assert contract.symbol == "SPY"

    @pytest.mark.asyncio
    async def test_uncertain_data_returns_no_contract(self) -> None:
        """Uncertain market data (0.40 < score < 0.60) → no signal."""
        analyst, q = self._make_analyst()
        analyst._fetch_market_data = AsyncMock(return_value=_uncertain_market_data())

        with patch("core.kill_switch.is_blocked", return_value=False):
            with patch("core.logging.append_jsonl"):
                wake_event = MagicMock()
                wake_event.trigger = "SCHEDULE"
                wake_event.raw = None
                raw = await analyst.gather_data(wake_event)
                evidence = await analyst.build_evidence(raw)
                contract = await analyst.select_contract(evidence, raw)

        assert contract is None

    @pytest.mark.asyncio
    async def test_atm_strike_selection(self) -> None:
        """ATM strike rounds to nearest dollar."""
        analyst, q = self._make_analyst()
        data = _bullish_market_data()
        data["spy_price"] = 581.73
        analyst._fetch_market_data = AsyncMock(return_value=data)

        with patch("core.kill_switch.is_blocked", return_value=False):
            with patch("core.logging.append_jsonl"):
                wake_event = MagicMock()
                wake_event.trigger = "SCHEDULE"
                wake_event.raw = None
                raw = await analyst.gather_data(wake_event)
                evidence = await analyst.build_evidence(raw)
                contract = await analyst.select_contract(evidence, raw)

        assert contract is not None
        assert contract.strike == 582.0  # rounds to nearest dollar

    @pytest.mark.asyncio
    async def test_no_data_returns_none(self) -> None:
        """No market data → no contract."""
        analyst, q = self._make_analyst()
        analyst._fetch_market_data = AsyncMock(return_value=None)

        wake_event = MagicMock()
        wake_event.trigger = "SCHEDULE"
        wake_event.raw = None
        raw = await analyst.gather_data(wake_event)
        assert raw is None


# ─── Helper function tests ────────────────────────────────────────────────────

class TestNearestFriday:
    def test_friday_returns_same_day(self) -> None:
        # 2026-06-12 is a Friday
        fri = date(2026, 6, 12)
        assert nearest_friday(fri) == fri

    def test_monday_returns_next_friday(self) -> None:
        # 2026-06-15 is a Monday
        mon = date(2026, 6, 15)
        result = nearest_friday(mon)
        assert result == date(2026, 6, 19)

    def test_thursday_returns_next_day(self) -> None:
        # 2026-06-18 is a Thursday
        thu = date(2026, 6, 18)
        result = nearest_friday(thu)
        assert result == date(2026, 6, 19)


class TestATMStrike:
    def test_rounds_down(self) -> None:
        assert atm_strike(580.4) == 580.0

    def test_rounds_up(self) -> None:
        assert atm_strike(580.6) == 581.0

    def test_exactly_on_strike(self) -> None:
        assert atm_strike(582.0) == 582.0


# ─── Config alignment ─────────────────────────────────────────────────────────

class TestConfig:
    def test_analyst_id_matches_config(self) -> None:
        import json
        from pathlib import Path
        cfg_path = Path("configs/analysts/spy_spx_uw.json")
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            assert cfg["analyst_id"] == SPYSPXUWAnalyst._ANALYST_ID

    def test_exit_rules_is_ta_rules(self) -> None:
        q: asyncio.Queue[TradeSignal] = asyncio.Queue()
        analyst = SPYSPXUWAnalyst(signal_queue=q)
        assert analyst.exit_rules.strategy == "TA_RULES"

    def test_wake_interval_is_300(self) -> None:
        q: asyncio.Queue[TradeSignal] = asyncio.Queue()
        analyst = SPYSPXUWAnalyst(signal_queue=q)
        assert analyst.wake_interval_seconds == 300

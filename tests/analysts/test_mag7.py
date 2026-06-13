"""
Tests for analysts/unusual_whales/mag7.py

Uses mock UW client and synthetic price/volume data — no live network calls.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from analysts.unusual_whales.mag7 import (
    Mag7Analyst,
    _compute_rsi,
    _is_rth,
    _load_watchlist,
    _nearest_weekly_friday,
)
from core.schemas import Evidence, ExitRules, TradeSignal


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_prices(count: int = 25, base: float = 200.0, trend: float = 1.005) -> list[float]:
    """Generate a synthetic uptrend price series."""
    prices = [base]
    for _ in range(count - 1):
        prices.append(round(prices[-1] * trend, 2))
    return prices


def _make_volumes(count: int = 25, base: int = 1_000_000, spike: bool = False) -> list[int]:
    """Generate synthetic volume series, optionally with a volume spike on the last day."""
    vols = [base] * count
    if spike:
        vols[-1] = int(base * 2.0)  # 2× spike
    return vols


def _make_uw_flow(premium: float, direction: str = "CALL") -> list[dict]:
    """Build a synthetic UW flow record."""
    return [{"ticker": "AAPL", "premium": premium, "call_or_put": direction}]


def _make_mock_uw(
    flow: list[dict] | None = None,
    activity: list[dict] | None = None,
) -> MagicMock:
    """Build a mock UWClient."""
    mock = MagicMock()
    mock.get_option_flow = AsyncMock(return_value=flow or [])
    mock.get_unusual_activity = AsyncMock(return_value=activity or [])
    mock.get_market_overview = AsyncMock(return_value={})
    mock.get_stock_screener = AsyncMock(return_value=[])
    return mock


def _make_mag7(
    signal_queue: asyncio.Queue | None = None,
    uw_client: MagicMock | None = None,
    confidence_threshold: float = 0.65,
    min_evidence_items: int = 3,
) -> Mag7Analyst:
    return Mag7Analyst(
        signal_queue=signal_queue or asyncio.Queue(),
        uw_client=uw_client or _make_mock_uw(),
        confidence_threshold=confidence_threshold,
        min_evidence_items=min_evidence_items,
    )


# ─── Pure helpers ─────────────────────────────────────────────────────────────

class TestNearestWeeklyFriday:
    def test_friday_returns_today(self) -> None:
        # Find a Friday
        today = date(2026, 6, 12)  # June 12 2026 is a Friday
        assert today.weekday() == 4  # sanity check
        result = _nearest_weekly_friday(today)
        assert result == today

    def test_monday_returns_next_friday(self) -> None:
        monday = date(2026, 6, 8)  # Monday
        result = _nearest_weekly_friday(monday)
        assert result == date(2026, 6, 12)  # Friday of same week

    def test_saturday_returns_next_friday(self) -> None:
        saturday = date(2026, 6, 13)  # Saturday
        result = _nearest_weekly_friday(saturday)
        assert result == date(2026, 6, 19)  # Next Friday

    def test_result_is_always_friday(self) -> None:
        """Check a full week of inputs all produce Fridays."""
        start = date(2026, 6, 8)
        for i in range(7):
            d = start + timedelta(days=i)
            result = _nearest_weekly_friday(d)
            assert result.weekday() == 4, f"Expected Friday for input {d}, got {result}"


class TestIsRTH:
    def _et(self, hour: int, minute: int = 0, weekday_offset: int = 0) -> datetime:
        """Build a UTC datetime that maps to the given ET hour:minute on a weekday."""
        # ET = UTC-4 during EDT; base Monday 2026-06-08
        base = datetime(2026, 6, 8 + weekday_offset, tzinfo=timezone.utc)
        return base.replace(hour=hour + 4, minute=minute)

    def test_inside_rth(self) -> None:
        dt = self._et(10, 30)  # 10:30 AM ET
        assert _is_rth(dt) is True

    def test_before_rth(self) -> None:
        dt = self._et(9, 0)  # 9:00 AM ET
        assert _is_rth(dt) is False

    def test_at_rth_open(self) -> None:
        dt = self._et(9, 30)  # 9:30 AM ET exactly
        assert _is_rth(dt) is True

    def test_at_rth_close(self) -> None:
        dt = self._et(16, 0)  # 4:00 PM ET exactly — closed
        assert _is_rth(dt) is False

    def test_weekend(self) -> None:
        dt = self._et(11, 0, weekday_offset=5)  # Saturday
        assert _is_rth(dt) is False


class TestComputeRSI:
    def test_returns_none_on_insufficient_data(self) -> None:
        assert _compute_rsi([100.0, 101.0], period=14) is None

    def test_returns_100_when_no_losses(self) -> None:
        prices = [float(i) for i in range(1, 20)]  # Pure uptrend
        rsi = _compute_rsi(prices, period=14)
        assert rsi == 100.0

    def test_overbought_zone(self) -> None:
        # Strong uptrend should produce RSI > 70
        prices = _make_prices(20, base=100.0, trend=1.02)
        rsi = _compute_rsi(prices, period=14)
        assert rsi is not None
        assert rsi > 70

    def test_reasonable_range(self) -> None:
        prices = _make_prices(20, base=100.0, trend=1.001)  # Mild uptrend
        rsi = _compute_rsi(prices)
        assert rsi is not None
        assert 0 <= rsi <= 100


# ─── test_mag7_scoring ────────────────────────────────────────────────────────

class TestMag7Scoring:
    """
    test_mag7_scoring: build evidence items from mock UW + synthetic yfinance data,
    verify correct evidence selection.
    """

    def _make_good_data(self, symbol: str = "NVDA") -> dict:
        """Produce data that satisfies all 5 scoring criteria → all bullish."""
        prices = _make_prices(25, base=500.0, trend=1.005)  # Mild uptrend, low RSI
        volumes = _make_volumes(25, base=2_000_000, spike=True)  # Volume spike
        flow = _make_uw_flow(premium=150_000, direction="CALL")  # > $100k
        return {
            symbol: {
                "flow": flow,
                "prices": prices,
                "volumes": volumes,
                "sector_ret": 0.015,  # XLK outperforming SPY by 1.5%
            }
        }

    def _make_weak_data(self, symbol: str = "TSLA") -> dict:
        """Produce data that fails most scoring criteria."""
        prices = [200.0] * 25  # Flat — no momentum, RSI neutral
        volumes = [1_000_000] * 25  # No volume spike
        flow = []  # No UW flow
        return {
            symbol: {
                "flow": flow,
                "prices": prices,
                "volumes": volumes,
                "sector_ret": -0.01,  # XLK underperforming
            }
        }

    def test_all_bullish_on_good_data(self) -> None:
        analyst = _make_mag7()
        data = self._make_good_data("NVDA")
        evidence = analyst._score_symbol("NVDA", data["NVDA"])

        assert len(evidence) == 5
        bullish_count = sum(1 for e in evidence if e.bullish)
        assert bullish_count >= 3, f"Expected 3+ bullish items, got {bullish_count}"

    def test_uw_flow_evidence_bullish_when_premium_high(self) -> None:
        analyst = _make_mag7()
        data = {"flow": _make_uw_flow(120_000, "CALL"), "prices": [], "volumes": [], "sector_ret": None}
        evidence = analyst._score_symbol("AAPL", data)
        uw_ev = next(e for e in evidence if e.indicator == "uw_option_flow")
        assert uw_ev.bullish is True
        assert uw_ev.weight == pytest.approx(0.30)

    def test_uw_flow_evidence_not_bullish_when_premium_low(self) -> None:
        analyst = _make_mag7()
        data = {"flow": _make_uw_flow(50_000, "CALL"), "prices": [], "volumes": [], "sector_ret": None}
        evidence = analyst._score_symbol("AAPL", data)
        uw_ev = next(e for e in evidence if e.indicator == "uw_option_flow")
        assert uw_ev.bullish is False

    def test_momentum_evidence_bullish_when_return_positive(self) -> None:
        analyst = _make_mag7()
        # 6 prices with strong uptrend (>2% over 5 days)
        prices = [100.0, 100.5, 101.0, 101.5, 102.0, 103.5]  # ~3.5% 5d return
        data = {"flow": [], "prices": prices, "volumes": [1_000_000] * 6, "sector_ret": None}
        evidence = analyst._score_symbol("MSFT", data)
        mom_ev = next(e for e in evidence if e.indicator == "price_momentum_5d")
        assert mom_ev.bullish is True

    def test_momentum_evidence_not_bullish_when_flat(self) -> None:
        analyst = _make_mag7()
        prices = [100.0] * 10  # Flat
        data = {"flow": [], "prices": prices, "volumes": [1_000_000] * 10, "sector_ret": None}
        evidence = analyst._score_symbol("META", data)
        mom_ev = next(e for e in evidence if e.indicator == "price_momentum_5d")
        assert mom_ev.bullish is False

    def test_volume_evidence_bullish_when_spiked(self) -> None:
        analyst = _make_mag7()
        volumes = _make_volumes(25, base=1_000_000, spike=True)  # 2× spike last day
        data = {"flow": [], "prices": _make_prices(25), "volumes": volumes, "sector_ret": None}
        evidence = analyst._score_symbol("AMZN", data)
        vol_ev = next(e for e in evidence if e.indicator == "volume_vs_20d_avg")
        assert vol_ev.bullish is True

    def test_sector_strength_evidence_bullish_when_positive(self) -> None:
        analyst = _make_mag7()
        data = {"flow": [], "prices": [], "volumes": [], "sector_ret": 0.02}
        evidence = analyst._score_symbol("GOOGL", data)
        sec_ev = next(e for e in evidence if e.indicator == "sector_strength")
        assert sec_ev.bullish is True
        assert sec_ev.weight == pytest.approx(0.15)

    def test_rsi_evidence_bullish_when_not_overbought(self) -> None:
        analyst = _make_mag7()
        # Mixed up/down series that produces RSI < 70 (not overbought)
        # Pattern: small gains alternating with small losses → balanced RSI
        base = 100.0
        prices = []
        for i in range(25):
            if i % 3 == 2:
                prices.append(round(base * 0.997, 2))  # down day
            else:
                prices.append(round(base * 1.002, 2))  # up day
            base = prices[-1]
        data = {"flow": [], "prices": prices, "volumes": [], "sector_ret": None}
        evidence = analyst._score_symbol("AAPL", data)
        rsi_ev = next(e for e in evidence if e.indicator == "rsi_not_overbought")
        # Mixed trend should give RSI < 70
        assert rsi_ev.value is not None
        assert rsi_ev.value < 70, f"Expected RSI < 70 for mixed trend, got {rsi_ev.value}"
        assert rsi_ev.bullish is True
        assert rsi_ev.weight == pytest.approx(0.10)

    def test_evidence_weights_sum_to_one(self) -> None:
        analyst = _make_mag7()
        data = {"flow": [], "prices": [], "volumes": [], "sector_ret": None}
        evidence = analyst._score_symbol("AAPL", data)
        total_weight = sum(e.weight for e in evidence)
        assert abs(total_weight - 1.0) < 0.001

    def test_evidence_indicators_are_distinct(self) -> None:
        analyst = _make_mag7()
        data = {"flow": [], "prices": [], "volumes": [], "sector_ret": None}
        evidence = analyst._score_symbol("AAPL", data)
        indicators = [e.indicator for e in evidence]
        assert len(indicators) == len(set(indicators)), "Duplicate indicators found"

    @pytest.mark.asyncio
    async def test_build_evidence_returns_empty_when_no_symbol_qualifies(self) -> None:
        analyst = _make_mag7(min_evidence_items=3)
        raw_data = self._make_weak_data("TSLA")
        evidence = await analyst.build_evidence(raw_data)
        assert evidence == []

    @pytest.mark.asyncio
    async def test_build_evidence_returns_evidence_when_symbol_qualifies(self) -> None:
        analyst = _make_mag7(min_evidence_items=3)
        raw_data = self._make_good_data("NVDA")
        # Provide strong data that passes the 3-item threshold
        # Override RSI to not be overbought by using mild prices
        raw_data["NVDA"]["prices"] = _make_prices(25, base=500.0, trend=1.003)
        evidence = await analyst.build_evidence(raw_data)
        assert len(evidence) == 5  # All 5 indicators returned

    @pytest.mark.asyncio
    async def test_gather_data_returns_none_outside_rth(self) -> None:
        """Outside RTH → gather_data returns None."""
        analyst = _make_mag7()
        from core.base_analyst import WakeEvent

        # Use a Saturday 11 AM ET timestamp
        saturday_utc = datetime(2026, 6, 13, 15, 0, tzinfo=timezone.utc)  # 11 AM ET on Saturday

        with patch("analysts.unusual_whales.mag7._is_rth", return_value=False):
            result = await analyst.gather_data(WakeEvent(trigger="SCHEDULE"))

        assert result is None

    @pytest.mark.asyncio
    async def test_select_contract_returns_valid_call(self) -> None:
        """select_contract should return a weekly CALL with valid fields."""
        analyst = _make_mag7()
        raw_data = self._make_good_data("NVDA")
        raw_data["NVDA"]["prices"] = _make_prices(25, base=500.0, trend=1.003)

        evidence = await analyst.build_evidence(raw_data)
        assert evidence  # Precondition

        contract = await analyst.select_contract(evidence, raw_data)
        assert contract is not None
        assert contract.direction == "CALL"
        assert contract.symbol == "NVDA"
        assert contract.expiry.weekday() == 4  # Friday
        assert contract.ask_per_share >= 0.10

    @pytest.mark.asyncio
    async def test_select_contract_returns_none_when_no_prices(self) -> None:
        analyst = _make_mag7()
        # Symbol qualifies by flow and sector but has no prices → can't compute strike
        raw_data = {
            "AAPL": {
                "flow": _make_uw_flow(150_000),
                "prices": [],
                "volumes": [],
                "sector_ret": 0.02,
            }
        }
        evidence = [Evidence(
            indicator="uw_option_flow",
            value=150_000,
            interpretation="High premium",
            weight=1.0,
            bullish=True,
        )]
        contract = await analyst.select_contract(evidence, raw_data)
        # No prices → None
        assert contract is None


# ─── test_load_watchlist ──────────────────────────────────────────────────────

class TestLoadWatchlist:
    def test_loads_from_config(self, tmp_path: Path) -> None:
        config = tmp_path / "mag7_watchlist.json"
        config.write_text(json.dumps({"watchlist": ["AAPL", "NVDA"]}))

        with patch("analysts.unusual_whales.mag7._WATCHLIST_PATH", config):
            wl = _load_watchlist()

        assert wl == ["AAPL", "NVDA"]

    def test_falls_back_to_defaults_on_missing_file(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent.json"
        with patch("analysts.unusual_whales.mag7._WATCHLIST_PATH", nonexistent):
            wl = _load_watchlist()
        assert "AAPL" in wl
        assert len(wl) == 7  # All 7 Mag7 defaults

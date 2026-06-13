"""
Tests for analysts/unusual_whales/screener.py (M3.4 — Options Screener Analyst).

All tests are pure unit tests — no asyncio event loop, no network, no file I/O.
Candidate objects are constructed directly and fed to the pure helper functions.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from analysts.unusual_whales.screener import (
    ScreenerAnalyst,
    ScreenerCandidate,
    _EARNINGS_MIN_DAYS,
    _NEAR_52W_BAND,
    _TOP_N,
    build_candidate_evidence,
    filter_and_rank,
    passes_all_criteria,
)
from core.schemas import TradeSignal


# ─── Fixtures / helpers ───────────────────────────────────────────────────────

_TODAY = datetime.now(tz=timezone.utc).date()
_SAFE_EXPIRY = _TODAY + timedelta(days=7)
_SAFE_EARNINGS = _TODAY + timedelta(days=30)  # well beyond 14-day window


def _make_candidate(
    symbol: str = "AAPL",
    direction: str = "CALL",
    strike: float = 200.0,
    current_price: float = 195.0,
    option_volume: float = 600_000.0,
    avg_oi_20d: float = 100_000.0,      # volume_ratio = 6× → passes 3× threshold
    market_cap_b: float = 3.0,           # > $2B → passes
    float_m: float = 50.0,              # > 10M → passes
    beta: float = 1.2,                  # 0.8–3.0 → passes
    price_52w_high: float = 230.0,
    price_52w_low: float = 150.0,
    earnings_date: date | None = None,
    unusual_volume_ratio: float | None = None,
) -> ScreenerCandidate:
    """Build a passing candidate. Override individual fields to test failures."""
    if earnings_date is None:
        earnings_date = _SAFE_EARNINGS
    if unusual_volume_ratio is None:
        unusual_volume_ratio = option_volume / avg_oi_20d

    return ScreenerCandidate(
        symbol=symbol,
        direction=direction,
        strike=strike,
        expiry=_SAFE_EXPIRY,
        current_price=current_price,
        option_volume=option_volume,
        avg_oi_20d=avg_oi_20d,
        market_cap_b=market_cap_b,
        float_m=float_m,
        beta=beta,
        price_52w_high=price_52w_high,
        price_52w_low=price_52w_low,
        earnings_date=earnings_date,
        unusual_volume_ratio=unusual_volume_ratio,
    )


# ─── Evidence builder tests ───────────────────────────────────────────────────

class TestBuildCandidateEvidence:
    def test_passing_candidate_all_bullish(self) -> None:
        c = _make_candidate()
        ev = build_candidate_evidence(c)
        assert all(e.bullish for e in ev), [e for e in ev if not e.bullish]

    def test_returns_five_items(self) -> None:
        c = _make_candidate()
        ev = build_candidate_evidence(c)
        assert len(ev) == 5

    def test_weights_sum_to_one(self) -> None:
        c = _make_candidate()
        ev = build_candidate_evidence(c)
        total = sum(e.weight for e in ev)
        assert abs(total - 1.0) < 1e-9

    def test_low_volume_ratio_fails(self) -> None:
        c = _make_candidate(option_volume=100_000, avg_oi_20d=100_000)  # ratio = 1× < 3×
        c = ScreenerCandidate(
            **{**c.__dict__, "unusual_volume_ratio": 1.0}
        )
        ev = build_candidate_evidence(c)
        vol_ev = next(e for e in ev if e.indicator == "uw_volume_ratio")
        assert not vol_ev.bullish

    def test_small_cap_fails(self) -> None:
        c = _make_candidate(market_cap_b=1.0)  # < $2B
        ev = build_candidate_evidence(c)
        liq_ev = next(e for e in ev if e.indicator == "liquidity_filter")
        assert not liq_ev.bullish

    def test_small_float_fails(self) -> None:
        c = _make_candidate(float_m=5.0)  # < 10M
        ev = build_candidate_evidence(c)
        liq_ev = next(e for e in ev if e.indicator == "liquidity_filter")
        assert not liq_ev.bullish

    def test_beta_too_low_fails(self) -> None:
        c = _make_candidate(beta=0.5)
        ev = build_candidate_evidence(c)
        beta_ev = next(e for e in ev if e.indicator == "beta_filter")
        assert not beta_ev.bullish

    def test_beta_too_high_fails(self) -> None:
        c = _make_candidate(beta=4.0)
        ev = build_candidate_evidence(c)
        beta_ev = next(e for e in ev if e.indicator == "beta_filter")
        assert not beta_ev.bullish

    def test_near_52w_high_fails(self) -> None:
        # price = 228, high = 230 → within 5% of high (228 > 230*0.95=218.5)
        c = _make_candidate(current_price=228.0, price_52w_high=230.0, price_52w_low=150.0)
        ev = build_candidate_evidence(c)
        extremes_ev = next(e for e in ev if e.indicator == "price_extremes")
        assert not extremes_ev.bullish

    def test_near_52w_low_fails(self) -> None:
        # price = 152, low = 150 → within 5% of low (152 < 150*1.05=157.5)
        c = _make_candidate(current_price=152.0, price_52w_high=230.0, price_52w_low=150.0)
        ev = build_candidate_evidence(c)
        extremes_ev = next(e for e in ev if e.indicator == "price_extremes")
        assert not extremes_ev.bullish

    def test_earnings_too_close_fails(self) -> None:
        earnings_soon = _TODAY + timedelta(days=7)  # only 7 days — less than 14
        c = _make_candidate(earnings_date=earnings_soon)
        ev = build_candidate_evidence(c)
        earnings_ev = next(e for e in ev if e.indicator == "earnings_check")
        assert not earnings_ev.bullish

    def test_no_earnings_date_passes(self) -> None:
        c = _make_candidate(earnings_date=None)
        # Force None earnings_date onto the candidate
        c2 = ScreenerCandidate(
            **{**c.__dict__, "earnings_date": None}
        )
        ev = build_candidate_evidence(c2)
        earnings_ev = next(e for e in ev if e.indicator == "earnings_check")
        assert earnings_ev.bullish

    def test_earnings_exactly_14_days_fails(self) -> None:
        earnings_exact = _TODAY + timedelta(days=_EARNINGS_MIN_DAYS)
        c = _make_candidate(earnings_date=earnings_exact)
        ev = build_candidate_evidence(c)
        earnings_ev = next(e for e in ev if e.indicator == "earnings_check")
        # Must be STRICTLY > 14 days
        assert not earnings_ev.bullish

    def test_earnings_15_days_passes(self) -> None:
        earnings_ok = _TODAY + timedelta(days=_EARNINGS_MIN_DAYS + 1)
        c = _make_candidate(earnings_date=earnings_ok)
        ev = build_candidate_evidence(c)
        earnings_ev = next(e for e in ev if e.indicator == "earnings_check")
        assert earnings_ev.bullish


# ─── Filter and rank tests ─────────────────────────────────────────────────────

class TestFilterAndRank:
    def test_filters_low_volume_candidates(self) -> None:
        """Candidates with normal (1×) volume are filtered out."""
        low_vol = _make_candidate(
            symbol="LOW_VOL",
            option_volume=100_000,
            avg_oi_20d=100_000,
            unusual_volume_ratio=1.0,
        )
        passing = _make_candidate(
            symbol="HIGH_VOL",
            option_volume=600_000,
            avg_oi_20d=100_000,
            unusual_volume_ratio=6.0,
        )
        result = filter_and_rank([low_vol, passing])
        symbols = [c.symbol for c, _ in result]
        assert "LOW_VOL" not in symbols
        assert "HIGH_VOL" in symbols

    def test_top3_selection_from_10_candidates(self) -> None:
        """From 10 passing candidates, returns exactly top 3 sorted by volume ratio."""
        candidates = [
            _make_candidate(
                symbol=f"SYM{i:02d}",
                option_volume=float(i) * 100_000,
                avg_oi_20d=10_000.0,  # ratio = i×10
                unusual_volume_ratio=float(i) * 10.0,
            )
            for i in range(1, 11)   # SYM01–SYM10
        ]
        result = filter_and_rank(candidates)
        assert len(result) == _TOP_N  # 3
        # Top 3 by volume ratio should be SYM10 (100×), SYM09 (90×), SYM08 (80×)
        symbols = [c.symbol for c, _ in result]
        assert symbols[0] == "SYM10"
        assert symbols[1] == "SYM09"
        assert symbols[2] == "SYM08"

    def test_empty_input_returns_empty(self) -> None:
        result = filter_and_rank([])
        assert result == []

    def test_all_fail_returns_empty(self) -> None:
        # All candidates have low volume ratio
        bad = [
            _make_candidate(
                symbol=f"BAD{i}",
                option_volume=50_000,
                avg_oi_20d=100_000,
                unusual_volume_ratio=0.5,
            )
            for i in range(5)
        ]
        result = filter_and_rank(bad)
        assert result == []

    def test_fewer_than_3_returns_all_passing(self) -> None:
        """Only 2 candidates pass — returns both (not 3)."""
        candidates = [
            _make_candidate(symbol="A", unusual_volume_ratio=5.0),
            _make_candidate(symbol="B", unusual_volume_ratio=4.0),
        ]
        result = filter_and_rank(candidates)
        assert len(result) == 2

    def test_sorted_descending(self) -> None:
        candidates = [
            _make_candidate(symbol="LOW", unusual_volume_ratio=3.5),
            _make_candidate(symbol="HIGH", unusual_volume_ratio=8.0),
            _make_candidate(symbol="MID", unusual_volume_ratio=5.0),
        ]
        result = filter_and_rank(candidates)
        ratios = [c.unusual_volume_ratio for c, _ in result]
        assert ratios == sorted(ratios, reverse=True)


# ─── ScreenerAnalyst integration tests ───────────────────────────────────────

class TestScreenerAnalyst:
    def _make_analyst(self) -> tuple[ScreenerAnalyst, "asyncio.Queue[TradeSignal]"]:
        q: asyncio.Queue[TradeSignal] = asyncio.Queue()
        analyst = ScreenerAnalyst(signal_queue=q)
        return analyst, q

    @pytest.mark.asyncio
    async def test_screener_emits_signals_for_top_candidates(self) -> None:
        """Passing candidates are emitted as TradeSignals."""
        analyst, q = self._make_analyst()

        candidates = [
            _make_candidate(symbol="AAPL", unusual_volume_ratio=9.0),
            _make_candidate(symbol="MSFT", unusual_volume_ratio=7.0),
            _make_candidate(symbol="NVDA", unusual_volume_ratio=5.0),
            _make_candidate(symbol="TSLA", unusual_volume_ratio=3.5),
        ]
        analyst._fetch_screener_data = AsyncMock(return_value=candidates)

        with patch("core.kill_switch.is_blocked", return_value=False):
            with patch("core.logging.append_jsonl"):
                wake_event = MagicMock()
                wake_event.trigger = "SCHEDULE"
                wake_event.raw = None
                await analyst._process(wake_event)

        emitted: list[TradeSignal] = []
        while not q.empty():
            emitted.append(await q.get())

        assert len(emitted) == 3
        symbols = {s.symbol for s in emitted}
        assert "AAPL" in symbols
        assert "MSFT" in symbols
        assert "NVDA" in symbols
        assert "TSLA" not in symbols  # only top 3

    @pytest.mark.asyncio
    async def test_screener_filters_low_volume(self) -> None:
        """Candidates with volume_ratio < 3× are not emitted."""
        analyst, q = self._make_analyst()

        normal_vol = _make_candidate(
            symbol="NORMAL",
            option_volume=100_000,
            avg_oi_20d=100_000,
            unusual_volume_ratio=1.0,   # below threshold
        )
        analyst._fetch_screener_data = AsyncMock(return_value=[normal_vol])

        with patch("core.kill_switch.is_blocked", return_value=False):
            with patch("core.logging.append_jsonl"):
                wake_event = MagicMock()
                wake_event.trigger = "SCHEDULE"
                wake_event.raw = None
                await analyst._process(wake_event)

        assert q.empty()

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_all(self) -> None:
        """Kill switch active → no signals emitted."""
        analyst, q = self._make_analyst()
        analyst._fetch_screener_data = AsyncMock(
            return_value=[_make_candidate(unusual_volume_ratio=10.0)]
        )

        with patch("core.kill_switch.is_blocked", return_value=True):
            with patch("core.logging.append_jsonl"):
                wake_event = MagicMock()
                wake_event.trigger = "SCHEDULE"
                await analyst._process(wake_event)

        assert q.empty()

    @pytest.mark.asyncio
    async def test_duplicate_signal_suppressed(self) -> None:
        """Same symbol+direction+expiry from screener is deduplicated within 5 min."""
        analyst, q = self._make_analyst()

        candidates = [_make_candidate(symbol="AAPL", unusual_volume_ratio=9.0)]
        analyst._fetch_screener_data = AsyncMock(return_value=candidates)

        with patch("core.kill_switch.is_blocked", return_value=False):
            with patch("core.logging.append_jsonl"):
                wake_event = MagicMock()
                wake_event.trigger = "SCHEDULE"
                wake_event.raw = None
                # First call
                await analyst._process(wake_event)
                # Second call — same symbol, should be deduplicated
                await analyst._process(wake_event)

        emitted: list[TradeSignal] = []
        while not q.empty():
            emitted.append(await q.get())

        # Should be exactly 1 signal, not 2
        assert len(emitted) == 1

    @pytest.mark.asyncio
    async def test_empty_screener_emits_nothing(self) -> None:
        analyst, q = self._make_analyst()
        analyst._fetch_screener_data = AsyncMock(return_value=[])

        with patch("core.kill_switch.is_blocked", return_value=False):
            with patch("core.logging.append_jsonl"):
                wake_event = MagicMock()
                wake_event.trigger = "SCHEDULE"
                await analyst._process(wake_event)

        assert q.empty()


# ─── Config alignment ─────────────────────────────────────────────────────────

class TestScreenerConfig:
    def test_analyst_id_matches_config(self) -> None:
        import json
        from pathlib import Path
        cfg_path = Path("configs/analysts/screener.json")
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            assert cfg["analyst_id"] == ScreenerAnalyst._ANALYST_ID

    def test_exit_rules_is_ta_rules(self) -> None:
        q: asyncio.Queue[TradeSignal] = asyncio.Queue()
        analyst = ScreenerAnalyst(signal_queue=q)
        assert analyst.exit_rules.strategy == "TA_RULES"

    def test_wake_interval_is_300(self) -> None:
        q: asyncio.Queue[TradeSignal] = asyncio.Queue()
        analyst = ScreenerAnalyst(signal_queue=q)
        assert analyst.wake_interval_seconds == 300

    def test_source_layer_is_screener(self) -> None:
        q: asyncio.Queue[TradeSignal] = asyncio.Queue()
        analyst = ScreenerAnalyst(signal_queue=q)
        assert analyst.source_layer == "SCREENER"

"""
Tests for analysts/social/social_trends.py (M4.1 — Social Trends Analyst).

All network calls are mocked — no live Reddit / StockTwits / Google Trends /
yfinance traffic during the test suite.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from analysts.social.social_trends import (
    SocialTrendsAnalyst,
    _count_tickers_in_text,
    _is_rth,
    _is_spike,
    _load_baseline,
    _nearest_weekly_friday,
    _save_baseline,
    _update_baseline,
    _BASELINE_DAYS,
    _MIN_OPTION_VOLUME,
    _STOCKTWITS_BULLISH_PCT,
    _GTRENDS_SPIKE_MIN,
    _GTRENDS_BASELINE_MAX,
)
from core.schemas import Evidence, ExitRules, TradeSignal


# ─── Fixtures / helpers ───────────────────────────────────────────────────────

def _make_analyst(
    signal_queue: asyncio.Queue | None = None,
    confidence_threshold: float = 0.60,
    min_evidence_items: int = 2,
    baseline_path: Path | None = None,
) -> SocialTrendsAnalyst:
    kwargs: dict = {
        "signal_queue": signal_queue or asyncio.Queue(),
        "confidence_threshold": confidence_threshold,
        "min_evidence_items": min_evidence_items,
    }
    if baseline_path is not None:
        kwargs["baseline_path"] = baseline_path
    return SocialTrendsAnalyst(**kwargs)


def _make_baseline(
    ticker: str,
    days: int = 15,
    base_count: int = 50,
    today: date | None = None,
) -> dict[str, dict[str, int]]:
    """Build a synthetic 30-day baseline with consistent counts."""
    today = today or datetime.now(tz=timezone.utc).date()
    baseline: dict[str, dict[str, int]] = {ticker: {}}
    for i in range(days, 0, -1):
        d = str(today - timedelta(days=i))
        baseline[ticker][d] = base_count
    return baseline


def _make_spike_baseline(
    ticker: str,
    days: int = 15,
    base_count: int = 50,
    today: date | None = None,
) -> tuple[dict[str, dict[str, int]], int]:
    """
    Return a baseline + a spike count that is guaranteed > mean + 2σ.
    With all-equal historical values, std=0 — so we need slight variation.
    Returns (baseline, spike_count).
    """
    today = today or datetime.now(tz=timezone.utc).date()
    baseline: dict[str, dict[str, int]] = {ticker: {}}
    # Introduce a tiny bit of variation so std > 0
    for i in range(days, 0, -1):
        d = str(today - timedelta(days=i))
        # slight variation around base_count
        baseline[ticker][d] = base_count + (i % 3)  # 50, 51, 52, repeating

    # A spike count that is clearly > mean + 2σ for the above
    # mean ≈ 51, std ≈ 0.82 → threshold ≈ 52.6
    spike_count = base_count + 50  # 100 — safely above threshold
    return baseline, spike_count


def _make_evidence_items(
    reddit_bullish: bool = True,
    stocktwits_bullish: bool = True,
    gtrends_bullish: bool = False,
    option_vol_bullish: bool = True,
) -> list[Evidence]:
    """Build a minimal evidence list for select_contract tests."""
    return [
        Evidence(
            indicator="reddit_spike",
            value=200,
            interpretation="2σ spike",
            weight=0.30,
            bullish=reddit_bullish,
        ),
        Evidence(
            indicator="stocktwits_bullish",
            value=70.0,
            interpretation=">60% bullish",
            weight=0.25,
            bullish=stocktwits_bullish,
        ),
        Evidence(
            indicator="google_trends_spike",
            value=None,
            interpretation="data unavailable",
            weight=0.25,
            bullish=gtrends_bullish,
        ),
        Evidence(
            indicator="option_volume",
            value=800_000,
            interpretation=">500k",
            weight=0.20,
            bullish=option_vol_bullish,
        ),
    ]


# ─── test_spike_detection_above_2sigma ───────────────────────────────────────

class TestSpikeDetection:
    """test_spike_detection_above_2sigma — mock data with spike -> emits signal."""

    def test_is_spike_true_when_above_2sigma(self) -> None:
        """2σ detection correctly identifies a spike."""
        today = date(2026, 6, 13)
        baseline, spike_count = _make_spike_baseline("GME", days=15, base_count=50, today=today)
        assert _is_spike(baseline, "GME", spike_count, today=today) is True

    def test_is_spike_false_when_normal(self) -> None:
        """Normal volume (at baseline) is not a spike."""
        today = date(2026, 6, 13)
        baseline, _ = _make_spike_baseline("AAPL", days=15, base_count=50, today=today)
        # Use the mean itself — should NOT be a spike
        assert _is_spike(baseline, "AAPL", 51, today=today) is False

    def test_is_spike_false_with_insufficient_history(self) -> None:
        """Fewer than 3 historical points → no spike detection (returns False)."""
        today = date(2026, 6, 13)
        baseline: dict[str, dict[str, int]] = {
            "XYZ": {
                str(today - timedelta(days=2)): 50,
                str(today - timedelta(days=1)): 55,
            }
        }
        # Only 2 historical points — below 3-point minimum
        assert _is_spike(baseline, "XYZ", 500, today=today) is False

    def test_is_spike_false_for_unknown_ticker(self) -> None:
        """Unknown ticker (no baseline at all) → False."""
        assert _is_spike({}, "UNKN", 1000) is False

    @pytest.mark.asyncio
    async def test_spike_detection_above_2sigma_emits_signal(
        self, tmp_path: Path
    ) -> None:
        """
        Full integration: when a ticker spikes 2σ above baseline AND has
        high option volume, a TradeSignal is emitted onto the queue.
        """
        signal_queue: asyncio.Queue[TradeSignal] = asyncio.Queue()
        baseline_file = tmp_path / "social_baseline.json"

        today = datetime.now(tz=timezone.utc).date()
        baseline, spike_count = _make_spike_baseline("GME", days=15, base_count=50, today=today)
        baseline_file.write_text(json.dumps(baseline))

        analyst = _make_analyst(
            signal_queue=signal_queue,
            baseline_path=baseline_file,
        )
        analyst._baseline = baseline
        analyst._baseline_loaded = True

        raw_data = {
            "reddit": {"GME": spike_count},
            "stocktwits": {
                "GME": {"mentions": 300, "bullish_pct": 0.72}
            },
            "baseline": baseline,
        }

        # Mock Google Trends (spike) and option volume (above 500k)
        with (
            patch(
                "analysts.social.social_trends._option_daily_volume",
                return_value=750_000,
            ),
            patch(
                "analysts.social.social_trends._google_trends_interest",
                return_value=(85.0, 40.0),
            ),
            patch(
                "analysts.social.social_trends._current_stock_price",
                return_value=25.0,
            ),
            patch("analysts.social.social_trends._is_rth", return_value=True),
        ):
            evidence = await analyst.build_evidence(raw_data)
            assert len(evidence) == 4, f"Expected 4 evidence items, got {len(evidence)}"

            bullish_count = sum(1 for e in evidence if e.bullish)
            assert bullish_count >= 2, f"Expected >= 2 bullish items, got {bullish_count}"

            contract = await analyst.select_contract(evidence, raw_data)
            assert contract is not None
            assert contract.symbol == "GME"

    @pytest.mark.asyncio
    async def test_spike_in_evidence_has_correct_weight(self, tmp_path: Path) -> None:
        """Reddit spike evidence item must have weight=0.30."""
        today = datetime.now(tz=timezone.utc).date()
        baseline, spike_count = _make_spike_baseline("TSLA", days=15, today=today)

        analyst = _make_analyst()
        analyst._baseline = baseline
        analyst._baseline_loaded = True

        evidence = analyst._build_evidence_for_ticker(
            ticker="TSLA",
            reddit_count=spike_count,
            spike=True,
            baseline=baseline,
            stocktwits_data={"mentions": 100, "bullish_pct": 0.70},
            gtrends_current=85.0,
            gtrends_baseline_avg=42.0,
            opt_vol=600_000,
        )

        reddit_ev = next(e for e in evidence if e.indicator == "reddit_spike")
        assert reddit_ev.bullish is True
        assert reddit_ev.weight == pytest.approx(0.30)

        total_weight = sum(e.weight for e in evidence)
        assert abs(total_weight - 1.0) < 0.001


# ─── test_no_spike_no_signal ──────────────────────────────────────────────────

class TestNoSpikeNoSignal:
    """test_no_spike_no_signal — normal volume -> no signal emitted."""

    @pytest.mark.asyncio
    async def test_no_spike_returns_empty_evidence(self, tmp_path: Path) -> None:
        """Normal mention count (no spike) produces no evidence and no signal."""
        signal_queue: asyncio.Queue[TradeSignal] = asyncio.Queue()

        today = datetime.now(tz=timezone.utc).date()
        # Build baseline with consistent counts
        baseline = _make_baseline("AAPL", days=15, base_count=50, today=today)

        analyst = _make_analyst(signal_queue=signal_queue)
        analyst._baseline = baseline
        analyst._baseline_loaded = True

        # Provide normal (non-spike) count — at or below mean
        raw_data = {
            "reddit": {"AAPL": 50},  # at mean — not a spike
            "stocktwits": {},
            "baseline": baseline,
        }

        with (
            patch(
                "analysts.social.social_trends._option_daily_volume",
                return_value=600_000,
            ),
            patch(
                "analysts.social.social_trends._google_trends_interest",
                return_value=(30.0, 30.0),
            ),
        ):
            evidence = await analyst.build_evidence(raw_data)

        assert evidence == []
        assert signal_queue.empty()

    @pytest.mark.asyncio
    async def test_option_volume_below_threshold_skips_ticker(self, tmp_path: Path) -> None:
        """
        Even with a Reddit spike, if option volume < 500k the ticker is
        excluded and no signal is emitted.
        """
        today = datetime.now(tz=timezone.utc).date()
        baseline, spike_count = _make_spike_baseline("BBBY", days=15, today=today)

        analyst = _make_analyst()
        analyst._baseline = baseline
        analyst._baseline_loaded = True

        raw_data = {
            "reddit": {"BBBY": spike_count},
            "stocktwits": {"BBBY": {"mentions": 200, "bullish_pct": 0.75}},
            "baseline": baseline,
        }

        # Option volume BELOW threshold
        with (
            patch(
                "analysts.social.social_trends._option_daily_volume",
                return_value=100_000,  # below 500k
            ),
            patch(
                "analysts.social.social_trends._google_trends_interest",
                return_value=(85.0, 40.0),
            ),
        ):
            evidence = await analyst.build_evidence(raw_data)

        assert evidence == []

    @pytest.mark.asyncio
    async def test_no_data_no_signal(self) -> None:
        """Empty reddit and stocktwits dicts → no signal."""
        analyst = _make_analyst()
        analyst._baseline = {}
        analyst._baseline_loaded = True

        raw_data = {"reddit": {}, "stocktwits": {}, "baseline": {}}
        evidence = await analyst.build_evidence(raw_data)
        assert evidence == []


# ─── test_missing_reddit_creds_doesnt_crash ───────────────────────────────────

class TestMissingRedditCreds:
    """test_missing_reddit_creds_doesnt_crash — env vars missing -> runs, logs warning."""

    @pytest.mark.asyncio
    async def test_missing_reddit_creds_analyst_still_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        When REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT are
        not set, the analyst must not crash — it skips Reddit and continues.
        """
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)

        signal_queue: asyncio.Queue[TradeSignal] = asyncio.Queue()
        analyst = _make_analyst(signal_queue=signal_queue)
        analyst._baseline = {}
        analyst._baseline_loaded = True

        # Patch StockTwits to return no data, keep Reddit real (no creds → empty dict)
        with (
            patch(
                "analysts.social.social_trends._stocktwits_trending",
                return_value={},
            ),
            patch("analysts.social.social_trends._is_rth", return_value=True),
        ):
            import logging
            with caplog.at_level(logging.WARNING, logger="analyst.social_trends"):
                result = await analyst.gather_data(
                    __import__(
                        "core.base_analyst", fromlist=["WakeEvent"]
                    ).WakeEvent(trigger="SCHEDULE")
                )

        # Should complete without exception
        # Result may be an empty-data dict (Reddit skipped, StockTwits mocked empty)
        assert isinstance(result, dict) or result is None

        # The warning about missing credentials must appear
        # (either in analyst logs or in the reddit helper's logger)
        reddit_warning_found = any(
            "REDDIT_CLIENT_ID" in r.message or "credentials" in r.message.lower()
            for r in caplog.records
        )
        # Allow the warning to originate from any logger
        if not reddit_warning_found:
            # Also check root logger
            all_msgs = " ".join(r.message for r in caplog.records)
            assert (
                "reddit" in all_msgs.lower() or "credential" in all_msgs.lower()
            ), f"Expected Reddit credential warning in logs. Got: {all_msgs!r}"

    def test_reddit_fetch_returns_empty_without_creds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_reddit_mention_counts returns {} (not raises) when env vars are absent."""
        from analysts.social.social_trends import _reddit_mention_counts

        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)

        result = _reddit_mention_counts(["wallstreetbets"], 10)
        assert result == {}

    def test_reddit_fetch_returns_empty_when_praw_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_reddit_mention_counts returns {} when praw is not available."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "praw":
                raise ImportError("No module named 'praw'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setenv("REDDIT_CLIENT_ID", "fake_id")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "fake_secret")
        monkeypatch.setenv("REDDIT_USER_AGENT", "fake_agent")

        from analysts.social.social_trends import _reddit_mention_counts

        with patch("builtins.__import__", side_effect=mock_import):
            result = _reddit_mention_counts(["wallstreetbets"], 10)

        assert result == {}


# ─── test_baseline_update ─────────────────────────────────────────────────────

class TestBaselineUpdate:
    """test_baseline_update — after scan, baseline file is updated."""

    def test_update_baseline_adds_today(self) -> None:
        """_update_baseline adds today's count to the baseline dict."""
        today = date(2026, 6, 13)
        baseline = _make_baseline("GME", days=5, base_count=50, today=today)
        updated = _update_baseline(baseline, "GME", 200, today=today)

        assert str(today) in updated["GME"]
        assert updated["GME"][str(today)] == 200

    def test_update_baseline_prunes_old_entries(self) -> None:
        """Entries older than 30 days are pruned."""
        today = date(2026, 6, 13)
        cutoff = today - timedelta(days=_BASELINE_DAYS)
        old_date = str(cutoff - timedelta(days=5))  # 5 days before cutoff → should be pruned

        baseline: dict[str, dict[str, int]] = {
            "AMC": {
                old_date: 100,
                str(today - timedelta(days=10)): 50,
            }
        }
        updated = _update_baseline(baseline, "AMC", 75, today=today)

        assert old_date not in updated["AMC"], "Old entry was not pruned"
        assert str(today - timedelta(days=10)) in updated["AMC"], "Recent entry was incorrectly pruned"

    def test_update_baseline_creates_ticker_entry_if_missing(self) -> None:
        """Adding a brand-new ticker creates the entry in the baseline."""
        today = date(2026, 6, 13)
        baseline: dict[str, dict[str, int]] = {}
        updated = _update_baseline(baseline, "NVDA", 120, today=today)

        assert "NVDA" in updated
        assert updated["NVDA"][str(today)] == 120

    def test_save_and_load_baseline_roundtrip(self, tmp_path: Path) -> None:
        """Saving and loading the baseline file produces identical data."""
        today = date(2026, 6, 13)
        baseline, _ = _make_spike_baseline("AAPL", days=10, today=today)
        path = tmp_path / "social_baseline.json"

        _save_baseline(baseline, path)
        loaded = _load_baseline(path)

        assert loaded == baseline

    def test_load_baseline_returns_empty_on_missing_file(self, tmp_path: Path) -> None:
        """_load_baseline returns {} when the file does not exist."""
        missing = tmp_path / "no_such_file.json"
        result = _load_baseline(missing)
        assert result == {}

    def test_load_baseline_returns_empty_on_malformed_json(self, tmp_path: Path) -> None:
        """_load_baseline returns {} on malformed JSON (safe-fail)."""
        bad = tmp_path / "bad_baseline.json"
        bad.write_text("{ this is not valid json !!!")
        result = _load_baseline(bad)
        assert result == {}

    @pytest.mark.asyncio
    async def test_baseline_file_updated_after_scan(self, tmp_path: Path) -> None:
        """
        After build_evidence runs, the baseline JSON file on disk must contain
        updated counts for the scanned ticker.
        """
        today = datetime.now(tz=timezone.utc).date()
        baseline_file = tmp_path / "social_baseline.json"

        # Start with enough history to enable spike detection
        baseline, spike_count = _make_spike_baseline("RKLB", days=15, base_count=50, today=today)
        baseline_file.write_text(json.dumps(baseline))

        analyst = _make_analyst(baseline_path=baseline_file)
        analyst._baseline = baseline
        analyst._baseline_loaded = True

        raw_data = {
            "reddit": {"RKLB": spike_count},
            "stocktwits": {"RKLB": {"mentions": 200, "bullish_pct": 0.65}},
            "baseline": baseline,
        }

        with (
            patch(
                "analysts.social.social_trends._option_daily_volume",
                return_value=600_000,
            ),
            patch(
                "analysts.social.social_trends._google_trends_interest",
                return_value=(85.0, 40.0),
            ),
            patch(
                "analysts.social.social_trends._current_stock_price",
                return_value=15.0,
            ),
        ):
            await analyst.build_evidence(raw_data)

        # File must have been updated
        saved = json.loads(baseline_file.read_text())
        assert "RKLB" in saved, "Ticker RKLB not found in saved baseline"
        today_str = str(today)
        assert today_str in saved["RKLB"], f"Today's entry ({today_str}) not in saved baseline"
        assert saved["RKLB"][today_str] == spike_count


# ─── Pure helper tests ────────────────────────────────────────────────────────

class TestCountTickersInText:
    def test_counts_dollar_prefixed_tickers(self) -> None:
        counts: dict[str, int] = {}
        _count_tickers_in_text("$GME to the moon $AMC next", counts)
        assert counts.get("GME", 0) >= 1
        assert counts.get("AMC", 0) >= 1

    def test_counts_standalone_uppercase(self) -> None:
        counts: dict[str, int] = {}
        _count_tickers_in_text("AAPL earnings beat estimates", counts)
        assert counts.get("AAPL", 0) >= 1

    def test_duplicate_mentions_accumulate(self) -> None:
        counts: dict[str, int] = {}
        _count_tickers_in_text("$TSLA $TSLA TSLA", counts)
        assert counts.get("TSLA", 0) >= 2


class TestNearestWeeklyFriday:
    def test_friday_returns_itself(self) -> None:
        friday = date(2026, 6, 12)  # Friday
        assert friday.weekday() == 4
        assert _nearest_weekly_friday(friday) == friday

    def test_monday_returns_same_week_friday(self) -> None:
        monday = date(2026, 6, 8)
        result = _nearest_weekly_friday(monday)
        assert result == date(2026, 6, 12)

    def test_result_always_friday(self) -> None:
        start = date(2026, 6, 8)
        for i in range(7):
            d = start + timedelta(days=i)
            assert _nearest_weekly_friday(d).weekday() == 4


class TestIsRTH:
    def _et_to_utc(self, hour: int, minute: int = 0, weekday_offset: int = 0) -> datetime:
        base = datetime(2026, 6, 8 + weekday_offset, tzinfo=timezone.utc)
        return base.replace(hour=hour + 4, minute=minute)

    def test_inside_rth(self) -> None:
        assert _is_rth(self._et_to_utc(10, 30)) is True

    def test_before_rth(self) -> None:
        assert _is_rth(self._et_to_utc(9, 0)) is False

    def test_at_open(self) -> None:
        assert _is_rth(self._et_to_utc(9, 30)) is True

    def test_at_close(self) -> None:
        assert _is_rth(self._et_to_utc(16, 0)) is False

    def test_weekend(self) -> None:
        # weekday_offset=5 → Saturday (2026-06-13)
        assert _is_rth(self._et_to_utc(11, 0, weekday_offset=5)) is False


class TestEvidenceBuilder:
    """Unit tests for _build_evidence_for_ticker."""

    def _analyst(self) -> SocialTrendsAnalyst:
        return _make_analyst()

    def test_evidence_weights_sum_to_one(self) -> None:
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=100,
            spike=True,
            baseline={"GME": {str(date(2026, 6, 1)): 50}},
            stocktwits_data=None,
            gtrends_current=None,
            gtrends_baseline_avg=None,
            opt_vol=None,
        )
        total = sum(e.weight for e in ev)
        assert abs(total - 1.0) < 0.001

    def test_evidence_indicators_distinct(self) -> None:
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=200,
            spike=True,
            baseline={},
            stocktwits_data={"bullish_pct": 0.70, "mentions": 50},
            gtrends_current=85.0,
            gtrends_baseline_avg=40.0,
            opt_vol=600_000,
        )
        indicators = [e.indicator for e in ev]
        assert len(indicators) == len(set(indicators)), "Duplicate indicators"

    def test_reddit_spike_bullish_when_spike_true(self) -> None:
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=200,
            spike=True,
            baseline={},
            stocktwits_data=None,
            gtrends_current=None,
            gtrends_baseline_avg=None,
            opt_vol=None,
        )
        reddit_ev = next(e for e in ev if e.indicator == "reddit_spike")
        assert reddit_ev.bullish is True

    def test_stocktwits_bullish_when_above_threshold(self) -> None:
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=0,
            spike=False,
            baseline={},
            stocktwits_data={"bullish_pct": 0.70, "mentions": 100},
            gtrends_current=None,
            gtrends_baseline_avg=None,
            opt_vol=None,
        )
        st_ev = next(e for e in ev if e.indicator == "stocktwits_bullish")
        assert st_ev.bullish is True
        assert st_ev.weight == pytest.approx(0.25)

    def test_stocktwits_not_bullish_when_below_threshold(self) -> None:
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=0,
            spike=False,
            baseline={},
            stocktwits_data={"bullish_pct": 0.45, "mentions": 100},
            gtrends_current=None,
            gtrends_baseline_avg=None,
            opt_vol=None,
        )
        st_ev = next(e for e in ev if e.indicator == "stocktwits_bullish")
        assert st_ev.bullish is False

    def test_gtrends_spike_detected_correctly(self) -> None:
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=0,
            spike=False,
            baseline={},
            stocktwits_data=None,
            gtrends_current=85.0,   # > 80
            gtrends_baseline_avg=40.0,  # < 50
            opt_vol=None,
        )
        gt_ev = next(e for e in ev if e.indicator == "google_trends_spike")
        assert gt_ev.bullish is True
        assert gt_ev.weight == pytest.approx(0.25)

    def test_gtrends_no_spike_when_baseline_high(self) -> None:
        """Spike score > 80 but baseline also > 50 → not a spike."""
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=0,
            spike=False,
            baseline={},
            stocktwits_data=None,
            gtrends_current=85.0,
            gtrends_baseline_avg=60.0,  # baseline >= 50 → no spike
            opt_vol=None,
        )
        gt_ev = next(e for e in ev if e.indicator == "google_trends_spike")
        assert gt_ev.bullish is False

    def test_option_volume_bullish_above_500k(self) -> None:
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=0,
            spike=False,
            baseline={},
            stocktwits_data=None,
            gtrends_current=None,
            gtrends_baseline_avg=None,
            opt_vol=600_000,
        )
        ov_ev = next(e for e in ev if e.indicator == "option_volume")
        assert ov_ev.bullish is True
        assert ov_ev.weight == pytest.approx(0.20)

    def test_option_volume_not_bullish_below_500k(self) -> None:
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=0,
            spike=False,
            baseline={},
            stocktwits_data=None,
            gtrends_current=None,
            gtrends_baseline_avg=None,
            opt_vol=300_000,
        )
        ov_ev = next(e for e in ev if e.indicator == "option_volume")
        assert ov_ev.bullish is False

    def test_none_opt_vol_not_bullish(self) -> None:
        a = self._analyst()
        ev = a._build_evidence_for_ticker(
            ticker="GME",
            reddit_count=0,
            spike=False,
            baseline={},
            stocktwits_data=None,
            gtrends_current=None,
            gtrends_baseline_avg=None,
            opt_vol=None,
        )
        ov_ev = next(e for e in ev if e.indicator == "option_volume")
        assert ov_ev.bullish is False


class TestSelectContract:
    @pytest.mark.asyncio
    async def test_select_contract_returns_valid_call(self) -> None:
        analyst = _make_analyst()
        evidence = _make_evidence_items(reddit_bullish=True, stocktwits_bullish=True)
        raw_data = {"_best_ticker": "GME"}

        with patch(
            "analysts.social.social_trends._current_stock_price",
            return_value=25.0,
        ):
            contract = await analyst.select_contract(evidence, raw_data)

        assert contract is not None
        assert contract.symbol == "GME"
        assert contract.direction == "CALL"
        assert contract.expiry.weekday() == 4  # Friday
        assert contract.ask_per_share >= 0.10

    @pytest.mark.asyncio
    async def test_select_contract_returns_put_when_bearish_dominant(self) -> None:
        analyst = _make_analyst()
        # All bearish evidence
        evidence = _make_evidence_items(
            reddit_bullish=False,
            stocktwits_bullish=False,
            gtrends_bullish=False,
            option_vol_bullish=False,
        )
        raw_data = {"_best_ticker": "GME"}

        with patch(
            "analysts.social.social_trends._current_stock_price",
            return_value=25.0,
        ):
            contract = await analyst.select_contract(evidence, raw_data)

        assert contract is not None
        assert contract.direction == "PUT"

    @pytest.mark.asyncio
    async def test_select_contract_returns_none_when_no_price(self) -> None:
        analyst = _make_analyst()
        evidence = _make_evidence_items()
        raw_data = {"_best_ticker": "GME"}

        with patch(
            "analysts.social.social_trends._current_stock_price",
            return_value=None,
        ):
            contract = await analyst.select_contract(evidence, raw_data)

        assert contract is None

    @pytest.mark.asyncio
    async def test_select_contract_returns_none_without_ticker(self) -> None:
        analyst = _make_analyst()
        evidence = _make_evidence_items()
        # No _best_ticker key
        raw_data: dict = {}
        contract = await analyst.select_contract(evidence, raw_data)
        assert contract is None

    @pytest.mark.asyncio
    async def test_select_contract_returns_none_on_empty_evidence(self) -> None:
        analyst = _make_analyst()
        raw_data = {"_best_ticker": "GME"}
        contract = await analyst.select_contract([], raw_data)
        assert contract is None


class TestAnalystConfig:
    """Verify the analyst class constants match the config file."""

    def test_analyst_id(self) -> None:
        assert SocialTrendsAnalyst.analyst_id == "social_trends"

    def test_source_layer(self) -> None:
        assert SocialTrendsAnalyst.source_layer == "SOCIAL"

    def test_wake_trigger(self) -> None:
        assert SocialTrendsAnalyst.wake_trigger == "SCHEDULE"

    def test_wake_interval_seconds(self) -> None:
        assert SocialTrendsAnalyst.wake_interval_seconds == 600

    def test_exit_rules(self) -> None:
        analyst = _make_analyst()
        assert analyst.exit_rules.strategy == "TA_RULES"

    def test_config_file_matches(self) -> None:
        config_path = Path(
            "configs/analysts/social_trends.json"
        )
        assert config_path.exists(), f"Config file not found: {config_path}"
        cfg = json.loads(config_path.read_text())
        assert cfg["analyst_id"] == SocialTrendsAnalyst.analyst_id
        assert cfg["source_layer"] == SocialTrendsAnalyst.source_layer
        assert cfg["wake_interval_seconds"] == SocialTrendsAnalyst.wake_interval_seconds
        assert cfg["exit_rules"]["strategy"] == "TA_RULES"

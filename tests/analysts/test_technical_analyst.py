"""
Tests for analysts/technical/technical_analyst.py (M4.2 — Technical Analyst).

All tests are pure unit tests — no live network calls, no real yfinance.
DataFrame fixtures are built with pandas directly.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from analysts.technical.technical_analyst import (
    TechnicalAnalyst,
    atm_strike,
    bullish_score_from_evidence,
    compute_cvd_evidence,
    compute_fvg_evidence,
    compute_obv_evidence,
    compute_put_call_evidence,
    compute_vix_evidence,
    compute_vwap_evidence,
    nearest_friday,
)
from core.schemas import Evidence, ExitRules, TradeSignal


# ─── DataFrame fixture helpers ────────────────────────────────────────────────

def _make_df(
    n: int = 20,
    open_: float = 580.0,
    close: float = 582.0,
    high: float = 583.0,
    low: float = 579.0,
    volume: float = 1_000_000,
) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame with `n` identical bars."""
    return pd.DataFrame({
        "Open":   [open_]  * n,
        "High":   [high]   * n,
        "Low":    [low]    * n,
        "Close":  [close]  * n,
        "Volume": [volume] * n,
    })


def _make_df_with_fvg_bullish(gap_size: float = 2.0) -> pd.DataFrame:
    """
    Create a DataFrame where bar[0].high < bar[2].low — a bullish FVG.

    Bar structure (simplified 3-bar FVG):
      bar 0: low=579, high=580   ← gap_high
      bar 1: (middle bar, ignored in FVG definition)
      bar 2: low=582 (> 580+gap_size) ← gap_low

    With current_price set just above bar[0].high, we should be in the FVG support zone.
    """
    rows = []
    # 17 neutral bars before
    for _ in range(17):
        rows.append({"Open": 580.0, "High": 583.0, "Low": 579.0, "Close": 581.0, "Volume": 1_000_000})
    # bar[i]: high=580 → this becomes gap_high
    rows.append({"Open": 579.0, "High": 580.0, "Low": 578.0, "Close": 579.5, "Volume": 1_000_000})
    # bar[i+1]: middle bar
    rows.append({"Open": 579.5, "High": 581.0, "Low": 579.0, "Close": 580.0, "Volume": 1_000_000})
    # bar[i+2]: low=582.5 → this becomes gap_low (582.5 > 580.0 = gap_high → bullish FVG)
    rows.append({"Open": 582.5, "High": 584.0, "Low": 582.5, "Close": 583.0, "Volume": 1_000_000})
    return pd.DataFrame(rows)


def _make_df_with_fvg_bearish() -> pd.DataFrame:
    """
    Create a DataFrame where bar[i+2].high < bar[i].low — a bearish FVG.

    Bar structure:
      bar i:   low=582 → gap_hi_bear
      bar i+1: middle bar
      bar i+2: high=580 (< 582) → gap_lo_bear

    With current_price near 582 (below gap_hi_bear), we enter the bearish resistance zone.
    """
    rows = []
    for _ in range(17):
        rows.append({"Open": 580.0, "High": 583.0, "Low": 578.0, "Close": 581.0, "Volume": 1_000_000})
    # bar[i]: low=582 → gap_hi_bear=582
    rows.append({"Open": 583.0, "High": 585.0, "Low": 582.0, "Close": 584.0, "Volume": 1_000_000})
    # bar[i+1]: middle bar
    rows.append({"Open": 583.5, "High": 584.0, "Low": 581.0, "Close": 582.0, "Volume": 1_000_000})
    # bar[i+2]: high=580 (< 582=gap_hi_bear) → bearish FVG
    rows.append({"Open": 580.5, "High": 580.0, "Low": 578.0, "Close": 579.0, "Volume": 1_000_000})
    return pd.DataFrame(rows)


def _make_analyst(tmp_path: Path) -> tuple[TechnicalAnalyst, "asyncio.Queue[TradeSignal]"]:
    q: asyncio.Queue[TradeSignal] = asyncio.Queue()
    analyst = TechnicalAnalyst(
        signal_queue=q,
        ta_signal_path=tmp_path / "ta_signal.json",
    )
    return analyst, q


# ─── FVG detection tests ──────────────────────────────────────────────────────

class TestFVGDetection:
    def test_fvg_bullish_detected_when_price_in_zone(self) -> None:
        """Bullish FVG: price just above gap_high → bullish Evidence returned."""
        df = _make_df_with_fvg_bullish()
        gap_high = 580.0
        # current_price = gap_high + 0.1% (inside 0.5% band)
        current_price = gap_high + gap_high * 0.001
        ev = compute_fvg_evidence(df, current_price)
        assert ev is not None, "Expected FVG evidence but got None"
        assert ev.bullish is True
        assert ev.indicator == "fvg"
        assert ev.weight == pytest.approx(0.20)

    def test_fvg_no_evidence_when_price_outside_zone(self) -> None:
        """Price far from any FVG zone → None returned."""
        df = _make_df(n=20, open_=580.0, close=582.0, high=583.0, low=579.0)
        # All bars identical — no gaps formed
        ev = compute_fvg_evidence(df, 581.0)
        assert ev is None

    def test_fvg_bearish_detected_when_price_near_resistance(self) -> None:
        """Bearish FVG: price just below gap_hi_bear → bearish Evidence."""
        df = _make_df_with_fvg_bearish()
        gap_hi_bear = 582.0
        # current_price = gap_hi_bear - 0.1% (inside 0.5% band)
        current_price = gap_hi_bear - gap_hi_bear * 0.001
        ev = compute_fvg_evidence(df, current_price)
        assert ev is not None, "Expected bearish FVG evidence but got None"
        assert ev.bullish is False
        assert ev.indicator == "fvg"

    def test_fvg_insufficient_data_returns_none(self) -> None:
        """Fewer than 3 bars → no FVG possible → None."""
        df = _make_df(n=2)
        ev = compute_fvg_evidence(df, 580.0)
        assert ev is None


# ─── VWAP tests ───────────────────────────────────────────────────────────────

class TestVWAP:
    def test_price_above_vwap_is_bullish(self) -> None:
        """Price > VWAP + 0.3% → bullish VWAP evidence."""
        # VWAP ≈ (high+low+close)/3 weighted by volume.
        # With all identical bars, VWAP = (583+579+582)/3 = 581.33...
        df = _make_df(open_=580.0, close=582.0, high=583.0, low=579.0)
        # Typical price ≈ 581.33; price=585 is clearly above + 0.3%
        ev = compute_vwap_evidence(df, current_price=585.0)
        assert ev.bullish is True
        assert ev.indicator == "vwap"
        assert ev.weight == pytest.approx(0.15)

    def test_price_below_vwap_is_bearish(self) -> None:
        """Price < VWAP - 0.3% → bearish VWAP evidence."""
        df = _make_df(open_=580.0, close=582.0, high=583.0, low=579.0)
        # typical ≈ 581.33; price=575 is clearly below -0.3%
        ev = compute_vwap_evidence(df, current_price=575.0)
        assert ev.bullish is False

    def test_price_at_vwap_is_neutral_bullish(self) -> None:
        """Price within ±0.3% of VWAP → neutral → leans bullish."""
        # All bars: H=581, L=581, C=581 → VWAP=581, price=581
        df = _make_df(open_=581.0, close=581.0, high=581.0, low=581.0)
        ev = compute_vwap_evidence(df, current_price=581.0)
        # deviation = 0% which is within ±0.3% → neutral → bullish=True
        assert ev.bullish is True


# ─── VIX tests ────────────────────────────────────────────────────────────────

class TestVIX:
    def test_vix_low_is_bullish(self) -> None:
        """VIX = 15 (< 20) → bullish."""
        ev = compute_vix_evidence(15.0)
        assert ev.bullish is True
        assert ev.indicator == "vix"
        assert ev.weight == pytest.approx(0.15)
        assert "low fear" in ev.interpretation

    def test_vix_high_is_bearish(self) -> None:
        """VIX = 30 (> 25) → bearish."""
        ev = compute_vix_evidence(30.0)
        assert ev.bullish is False
        assert "high fear" in ev.interpretation

    def test_vix_neutral_band_is_bullish(self) -> None:
        """VIX = 22 (20–25 neutral band) → lean bullish."""
        ev = compute_vix_evidence(22.0)
        assert ev.bullish is True

    def test_vix_exactly_20_is_bullish(self) -> None:
        """VIX = 20.0 (boundary) → bullish (< threshold uses strict <)."""
        ev = compute_vix_evidence(20.0)
        # 20.0 is NOT < 20.0, so it falls into neutral band
        assert ev.bullish is True


# ─── Put/Call ratio tests ─────────────────────────────────────────────────────

class TestPutCallRatio:
    def test_low_ratio_is_bullish(self) -> None:
        ev = compute_put_call_evidence(0.5)
        assert ev.bullish is True
        assert ev.indicator == "put_call_ratio"
        assert ev.weight == pytest.approx(0.20)

    def test_high_ratio_is_bearish(self) -> None:
        ev = compute_put_call_evidence(1.5)
        assert ev.bullish is False

    def test_neutral_ratio_is_bullish(self) -> None:
        ev = compute_put_call_evidence(1.0)
        assert ev.bullish is True


# ─── OBV tests ────────────────────────────────────────────────────────────────

class TestOBV:
    def test_rising_prices_yield_positive_obv_slope(self) -> None:
        """Steadily rising close prices → OBV slope > 0 → bullish."""
        df = pd.DataFrame({
            "Open":   [580.0 + i for i in range(10)],
            "High":   [582.0 + i for i in range(10)],
            "Low":    [579.0 + i for i in range(10)],
            "Close":  [581.0 + i for i in range(10)],  # rising
            "Volume": [1_000_000] * 10,
        })
        ev = compute_obv_evidence(df)
        assert ev.bullish is True
        assert ev.indicator == "obv"

    def test_falling_prices_yield_negative_obv_slope(self) -> None:
        """Steadily falling close prices → OBV slope < 0 → bearish."""
        df = pd.DataFrame({
            "Open":   [590.0 - i for i in range(10)],
            "High":   [592.0 - i for i in range(10)],
            "Low":    [588.0 - i for i in range(10)],
            "Close":  [590.0 - i for i in range(10)],  # falling
            "Volume": [1_000_000] * 10,
        })
        ev = compute_obv_evidence(df)
        assert ev.bullish is False


# ─── CVD tests ────────────────────────────────────────────────────────────────

class TestCVD:
    def test_bullish_candles_give_positive_cvd(self) -> None:
        """Candles where close > open → positive delta → CVD rising → bullish."""
        df = pd.DataFrame({
            "Open":   [580.0] * 10,
            "High":   [583.0] * 10,
            "Low":    [579.0] * 10,
            "Close":  [582.0] * 10,  # close > open
            "Volume": [1_000_000] * 10,
        })
        ev = compute_cvd_evidence(df)
        assert ev.bullish is True
        assert ev.indicator == "cvd"

    def test_bearish_candles_give_negative_cvd(self) -> None:
        """Candles where close < open → negative delta → CVD falling → bearish."""
        df = pd.DataFrame({
            "Open":   [582.0] * 10,
            "High":   [583.0] * 10,
            "Low":    [579.0] * 10,
            "Close":  [580.0] * 10,  # close < open
            "Volume": [1_000_000] * 10,
        })
        ev = compute_cvd_evidence(df)
        assert ev.bullish is False


# ─── TA signal file written after wake() ─────────────────────────────────────

class TestTASignalFileWritten:
    @pytest.mark.asyncio
    async def test_ta_signal_file_written_after_wake(self, tmp_path: Path) -> None:
        """After wake(), ta_signal.json must exist with required fields."""
        analyst, q = _make_analyst(tmp_path)
        analyst._running = True

        # Build minimal raw_data dict
        df = _make_df(n=20, open_=580.0, close=582.0, high=583.0, low=579.0)
        raw_data = {
            "df": df,
            "vix": 15.0,
            "put_call_ratio": 0.5,
            "current_price": 582.0,
        }

        analyst._fetch_spy_bars = AsyncMock(return_value=df)
        analyst._fetch_vix = AsyncMock(return_value=15.0)
        analyst._fetch_put_call_ratio = AsyncMock(return_value=0.5)

        sig_path = tmp_path / "ta_signal.json"

        with patch("core.kill_switch.is_blocked", return_value=False):
            with patch("core.logging.append_jsonl"):
                await analyst.wake(MagicMock(trigger="SCHEDULE", raw=None, channel_id=None))

        assert sig_path.exists(), "ta_signal.json was not written"
        data = json.loads(sig_path.read_text())

        # Required fields
        assert "timestamp" in data
        assert "symbol" in data
        assert data["symbol"] == "SPY"
        assert "direction" in data
        assert data["direction"] in ("CALL", "PUT", "HOLD")
        assert "confidence" in data
        assert "bullish_score" in data
        assert "evidence_count" in data
        assert isinstance(data["evidence_count"], int)
        assert data["evidence_count"] >= 1
        assert "indicators" in data

    @pytest.mark.asyncio
    async def test_ta_signal_written_on_hold(self, tmp_path: Path) -> None:
        """HOLD case: ta_signal.json is written even when no TradeSignal is emitted."""
        analyst, q = _make_analyst(tmp_path)

        # Perfectly balanced: half bullish, half bearish → score ≈ 0.5 → HOLD
        df = _make_df(n=20, open_=581.0, close=581.0, high=581.0, low=581.0)
        raw_data = {
            "df": df,
            "vix": 22.0,          # neutral → bullish
            "put_call_ratio": 1.0, # neutral → bullish
            "current_price": 581.0,
        }

        analyst._fetch_spy_bars = AsyncMock(return_value=df)
        analyst._fetch_vix = AsyncMock(return_value=22.0)
        analyst._fetch_put_call_ratio = AsyncMock(return_value=1.0)

        sig_path = tmp_path / "ta_signal.json"

        # Call select_contract directly with known balanced evidence
        evidence = await analyst.build_evidence(raw_data)
        await analyst.select_contract(evidence, raw_data)

        assert sig_path.exists()
        data = json.loads(sig_path.read_text())
        assert "direction" in data


# ─── HOLD: no TradeSignal emitted ─────────────────────────────────────────────

class TestHoldNoSignal:
    @pytest.mark.asyncio
    async def test_hold_no_signal_emitted(self, tmp_path: Path) -> None:
        """
        When indicators are balanced (score in 0.35–0.65 band),
        no TradeSignal is emitted but ta_signal.json is written with HOLD.
        """
        analyst, q = _make_analyst(tmp_path)
        analyst._running = True

        # Build data that produces a HOLD score:
        # VIX neutral (22) → bullish; P/C neutral (1.0) → bullish
        # OBV/CVD: flat close=open → CVD≈0, OBV slope≈0 → bullish (slope not negative)
        # VWAP: price at VWAP → neutral → bullish
        # Net: most lean bullish → we need to force a truly neutral scenario.
        # We'll patch select_contract via gather_data/build_evidence cycle and
        # override to simulate a score of 0.50.

        # Simplest: patch gather_data to return None so _process exits early.
        # Instead, let's test select_contract directly with constructed evidence.
        # 3 bullish (weight=0.45) and 3 bearish (weight=0.45) → score=0.5 → HOLD
        balanced_evidence = [
            Evidence(indicator="vwap", value=0, interpretation="above", weight=0.15, bullish=True),
            Evidence(indicator="vix", value=22.0, interpretation="neutral", weight=0.15, bullish=True),
            Evidence(indicator="obv", value=0, interpretation="flat", weight=0.15, bullish=True),
            Evidence(indicator="cvd", value=0, interpretation="flat", weight=0.15, bullish=False),
            Evidence(indicator="put_call_ratio", value=1.0, interpretation="neutral", weight=0.20, bullish=False),
            Evidence(indicator="fvg", value=0, interpretation="resistance", weight=0.20, bullish=False),
        ]

        raw_data = {"df": _make_df(), "vix": 22.0, "put_call_ratio": 1.0, "current_price": 581.0}

        sig_path = tmp_path / "ta_signal.json"
        result = await analyst.select_contract(balanced_evidence, raw_data)

        assert result is None, "HOLD should return None from select_contract"
        assert sig_path.exists()
        data = json.loads(sig_path.read_text())
        assert data["direction"] == "HOLD"
        assert q.empty(), "No TradeSignal should have been put in the queue"


# ─── Directional signal tests ─────────────────────────────────────────────────

class TestDirectionalSignals:
    @pytest.mark.asyncio
    async def test_strong_bullish_returns_call_contract(self, tmp_path: Path) -> None:
        """All bullish evidence → CALL contract returned."""
        analyst, q = _make_analyst(tmp_path)

        all_bullish = [
            Evidence(indicator="vwap", value=0, interpretation="above", weight=0.15, bullish=True),
            Evidence(indicator="vix", value=15.0, interpretation="low", weight=0.15, bullish=True),
            Evidence(indicator="obv", value=0, interpretation="rising", weight=0.15, bullish=True),
            Evidence(indicator="cvd", value=0, interpretation="rising", weight=0.15, bullish=True),
            Evidence(indicator="put_call_ratio", value=0.5, interpretation="bullish", weight=0.20, bullish=True),
            Evidence(indicator="fvg", value=0, interpretation="support", weight=0.20, bullish=True),
        ]

        raw_data = {"df": _make_df(), "vix": 15.0, "put_call_ratio": 0.5, "current_price": 582.0}
        contract = await analyst.select_contract(all_bullish, raw_data)

        assert contract is not None
        assert contract.direction == "CALL"
        assert contract.symbol == "SPY"

    @pytest.mark.asyncio
    async def test_strong_bearish_returns_put_contract(self, tmp_path: Path) -> None:
        """All bearish evidence → PUT contract returned."""
        analyst, q = _make_analyst(tmp_path)

        all_bearish = [
            Evidence(indicator="vwap", value=0, interpretation="below", weight=0.15, bullish=False),
            Evidence(indicator="vix", value=30.0, interpretation="high fear", weight=0.15, bullish=False),
            Evidence(indicator="obv", value=0, interpretation="falling", weight=0.15, bullish=False),
            Evidence(indicator="cvd", value=0, interpretation="falling", weight=0.15, bullish=False),
            Evidence(indicator="put_call_ratio", value=1.5, interpretation="bearish", weight=0.20, bullish=False),
            Evidence(indicator="fvg", value=0, interpretation="resistance", weight=0.20, bullish=False),
        ]

        raw_data = {"df": _make_df(), "vix": 30.0, "put_call_ratio": 1.5, "current_price": 578.0}
        contract = await analyst.select_contract(all_bearish, raw_data)

        assert contract is not None
        assert contract.direction == "PUT"


# ─── get_current_signal ───────────────────────────────────────────────────────

class TestGetCurrentSignal:
    @pytest.mark.asyncio
    async def test_returns_dict_when_file_exists(self, tmp_path: Path) -> None:
        analyst, _ = _make_analyst(tmp_path)
        sig_path = tmp_path / "ta_signal.json"
        payload = {"direction": "CALL", "confidence": 0.75, "symbol": "SPY",
                   "bullish_score": 0.75, "evidence_count": 5,
                   "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                   "indicators": {}}
        sig_path.write_text(json.dumps(payload))

        result = await analyst.get_current_signal()
        assert result["direction"] == "CALL"
        assert result["confidence"] == 0.75

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        analyst, _ = _make_analyst(tmp_path)
        result = await analyst.get_current_signal()
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_malformed_json(self, tmp_path: Path) -> None:
        analyst, _ = _make_analyst(tmp_path)
        (tmp_path / "ta_signal.json").write_text("not json {{{")
        result = await analyst.get_current_signal()
        assert result == {}


# ─── Config alignment ─────────────────────────────────────────────────────────

class TestConfig:
    def test_analyst_id_matches_config(self) -> None:
        cfg_path = Path("configs/analysts/technical.json")
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            assert cfg["analyst_id"] == TechnicalAnalyst._ANALYST_ID

    def test_exit_rules_is_ta_rules(self, tmp_path: Path) -> None:
        analyst, _ = _make_analyst(tmp_path)
        assert analyst.exit_rules.strategy == "TA_RULES"

    def test_wake_interval_is_300(self, tmp_path: Path) -> None:
        analyst, _ = _make_analyst(tmp_path)
        assert analyst.wake_interval_seconds == 300

    def test_source_layer_is_technical(self, tmp_path: Path) -> None:
        analyst, _ = _make_analyst(tmp_path)
        assert analyst.source_layer == "TECHNICAL"


# ─── Helper function tests ────────────────────────────────────────────────────

class TestNearestFriday:
    def test_friday_returns_same_day(self) -> None:
        # 2026-06-12 is a Friday
        fri = date(2026, 6, 12)
        assert nearest_friday(fri) == fri

    def test_monday_returns_next_friday(self) -> None:
        mon = date(2026, 6, 15)
        result = nearest_friday(mon)
        assert result == date(2026, 6, 19)

    def test_thursday_returns_next_day(self) -> None:
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


class TestBullishScore:
    def test_all_bullish_is_one(self) -> None:
        evs = [
            Evidence(indicator="a", value=1, interpretation="x", weight=0.5, bullish=True),
            Evidence(indicator="b", value=2, interpretation="y", weight=0.5, bullish=True),
        ]
        assert bullish_score_from_evidence(evs) == pytest.approx(1.0)

    def test_all_bearish_is_zero(self) -> None:
        evs = [
            Evidence(indicator="a", value=1, interpretation="x", weight=0.5, bullish=False),
            Evidence(indicator="b", value=2, interpretation="y", weight=0.5, bullish=False),
        ]
        assert bullish_score_from_evidence(evs) == pytest.approx(0.0)

    def test_empty_returns_zero(self) -> None:
        assert bullish_score_from_evidence([]) == 0.0

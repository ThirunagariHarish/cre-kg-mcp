"""
analysts/technical/technical_analyst.py — Technical Analyst (M4.2).

Computes multi-indicator signals for SPY/SPX using pure technical analysis.
Wakes every 5 minutes during RTH via SCHEDULE trigger.

Indicators (each becomes one Evidence item):
  1. Fair Value Gap (FVG)   weight=0.20 — price trading into gap zone
  2. VWAP deviation         weight=0.15 — price vs session VWAP ± 0.3%
  3. OBV trend              weight=0.15 — 5-bar OBV slope direction
  4. CVD (Cumulative Vol Δ) weight=0.15 — cumulative volume delta rising/falling
  5. VIX term structure     weight=0.15 — VIX < 20 → low fear → bullish
  6. Put/Call ratio trend   weight=0.20 — SPY options ratio < 0.7 bullish, > 1.3 bearish

Decision thresholds:
  bullish_score >= 0.65  → CALL — emit TradeSignal
  bullish_score <= 0.35  → PUT  — emit TradeSignal
  else                   → HOLD — write ta_signal.json, no signal emitted

TA signal file (shared/state/ta_signal.json):
  Read by MonitorAgent (TA_RULES exit strategy) and MasterAnalyst.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.base_analyst import BaseAnalyst, WakeEvent
from core.file_writer import atomic_write_json
from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    OptionDirection,
    TradeSignal,
)

logger = logging.getLogger("analyst.technical_ta")

# ─── Paths ────────────────────────────────────────────────────────────────────

_TA_SIGNAL_PATH = Path("shared/state/ta_signal.json")

# ─── Decision thresholds ──────────────────────────────────────────────────────

_BULLISH_THRESHOLD = 0.65
_BEARISH_THRESHOLD = 0.35

# ─── Indicator thresholds ─────────────────────────────────────────────────────

_VWAP_BAND_PCT = 0.003        # ±0.3%
_FVG_BAND_PCT = 0.005         # 0.5% proximity band
_OBV_WINDOW = 5               # 5-bar OBV slope
_VIX_LOW = 20.0               # below → low fear → bullish
_VIX_HIGH = 25.0              # above → high fear → bearish
_PC_BULLISH = 0.7             # put/call < 0.7 → bullish
_PC_BEARISH = 1.3             # put/call > 1.3 → bearish


# ─── Pure helpers (testable without asyncio) ─────────────────────────────────

def compute_fvg_evidence(df: "Any", current_price: float) -> Evidence | None:
    """
    Detect a Fair Value Gap from the last 20 5-minute candles.

    A FVG is a 3-candle pattern where candle[i+2].low > candle[i].high
    (bullish gap) or candle[i+2].high < candle[i].low (bearish gap).

    Returns an Evidence item if price is trading into a recent FVG zone,
    or None if no FVG is nearby.
    """
    try:
        highs = df["High"].values
        lows = df["Low"].values
        n = len(highs)
        if n < 3:
            return None

        # Scan last 20 bars (or all if fewer)
        start = max(0, n - 20)
        for i in range(start, n - 2):
            gap_low = lows[i + 2]    # bottom of bullish gap
            gap_high = highs[i]      # top of bullish gap (legacy: gap_high = candle[i].high)

            # Bullish FVG: gap_high < gap_low — the gap exists between bar[i] high and bar[i+2] low
            if gap_high < gap_low:
                # Price trading just above gap_high (support zone)
                band = gap_high * _FVG_BAND_PCT
                if gap_high <= current_price <= gap_high + band:
                    return Evidence(
                        indicator="fvg",
                        value={"gap_high": round(gap_high, 2), "gap_low": round(gap_low, 2),
                               "current": round(current_price, 2)},
                        interpretation=(
                            f"Bullish FVG support: price ${current_price:.2f} trading into "
                            f"gap zone ${gap_high:.2f}–${gap_low:.2f}"
                        ),
                        weight=0.20,
                        bullish=True,
                    )

            # Bearish FVG: highs[i+2] < lows[i] — gap between bar[i+2].high and bar[i].low
            gap_hi_bear = lows[i]      # top of bearish gap
            gap_lo_bear = highs[i + 2]  # bottom of bearish gap

            if gap_lo_bear < gap_hi_bear:
                # Price trading just below gap_hi_bear (resistance zone)
                band = gap_hi_bear * _FVG_BAND_PCT
                if gap_hi_bear - band <= current_price <= gap_hi_bear:
                    return Evidence(
                        indicator="fvg",
                        value={"gap_high": round(gap_hi_bear, 2), "gap_low": round(gap_lo_bear, 2),
                               "current": round(current_price, 2)},
                        interpretation=(
                            f"Bearish FVG resistance: price ${current_price:.2f} approaching "
                            f"gap zone ${gap_lo_bear:.2f}–${gap_hi_bear:.2f}"
                        ),
                        weight=0.20,
                        bullish=False,
                    )

        return None  # No FVG proximity found

    except Exception as exc:
        logger.debug("FVG computation failed: %s", exc)
        return None


def compute_vwap_evidence(df: "Any", current_price: float) -> Evidence:
    """
    VWAP from intraday 5-minute data.

    VWAP = Σ(typical_price × volume) / Σ(volume)
    typical_price = (high + low + close) / 3

    Returns a bullish Evidence if price > VWAP + 0.3%, bearish if below -0.3%.
    """
    try:
        highs = df["High"].values
        lows = df["Low"].values
        closes = df["Close"].values
        volumes = df["Volume"].values

        typical = (highs + lows + closes) / 3
        cum_tp_vol = (typical * volumes).sum()
        cum_vol = volumes.sum()

        vwap = cum_tp_vol / cum_vol if cum_vol > 0 else current_price

        deviation = (current_price - vwap) / vwap if vwap > 0 else 0.0
        bullish = deviation > _VWAP_BAND_PCT
        bearish_flag = deviation < -_VWAP_BAND_PCT

        if bullish:
            interp = f"Price ${current_price:.2f} is {deviation*100:.2f}% above VWAP ${vwap:.2f} — bullish momentum"
        elif bearish_flag:
            interp = f"Price ${current_price:.2f} is {deviation*100:.2f}% below VWAP ${vwap:.2f} — bearish momentum"
        else:
            interp = f"Price ${current_price:.2f} near VWAP ${vwap:.2f} ({deviation*100:.2f}%) — neutral"
            bullish = True  # neutral → lean bullish (market bias)

        return Evidence(
            indicator="vwap",
            value={"price": round(current_price, 2), "vwap": round(vwap, 4),
                   "deviation_pct": round(deviation * 100, 3)},
            interpretation=interp,
            weight=0.15,
            bullish=bullish,
        )

    except Exception as exc:
        logger.debug("VWAP computation failed: %s", exc)
        return Evidence(
            indicator="vwap",
            value={"error": str(exc)},
            interpretation="VWAP unavailable — defaulting neutral/bullish",
            weight=0.15,
            bullish=True,
        )


def compute_obv_evidence(df: "Any") -> Evidence:
    """
    On-Balance Volume: 5-bar OBV slope.

    OBV[i] = OBV[i-1] + volume if close > prev_close else -volume.
    Rising slope (last 5 bars) → bullish; falling → bearish.
    """
    try:
        closes = df["Close"].values
        volumes = df["Volume"].values

        if len(closes) < 2:
            return Evidence(
                indicator="obv",
                value=0,
                interpretation="Insufficient data for OBV",
                weight=0.15,
                bullish=True,
            )

        # Build OBV series
        obv = [0.0]
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                obv.append(obv[-1] + volumes[i])
            elif closes[i] < closes[i - 1]:
                obv.append(obv[-1] - volumes[i])
            else:
                obv.append(obv[-1])

        # 5-bar slope (last 5 OBV values)
        window = min(_OBV_WINDOW, len(obv))
        slope = obv[-1] - obv[-window]
        bullish = slope > 0

        return Evidence(
            indicator="obv",
            value={"obv_current": round(obv[-1], 0), "obv_5bar_slope": round(slope, 0)},
            interpretation=(
                f"OBV 5-bar slope {slope:+,.0f} — "
                f"{'rising (bullish accumulation)' if bullish else 'falling (bearish distribution)'}"
            ),
            weight=0.15,
            bullish=bullish,
        )

    except Exception as exc:
        logger.debug("OBV computation failed: %s", exc)
        return Evidence(
            indicator="obv",
            value={"error": str(exc)},
            interpretation="OBV unavailable — defaulting neutral/bullish",
            weight=0.15,
            bullish=True,
        )


def compute_cvd_evidence(df: "Any") -> Evidence:
    """
    Cumulative Volume Delta (CVD).

    Approximated as: delta_i = (close - open) / (high - low) * volume per candle.
    Rising CVD (slope > 0 over last 5 bars) → bullish; falling → bearish.
    """
    try:
        opens = df["Open"].values
        highs = df["High"].values
        lows = df["Low"].values
        closes = df["Close"].values
        volumes = df["Volume"].values

        ranges = highs - lows
        # Guard against zero-range candles (doji)
        ranges = [r if r > 0 else 0.001 for r in ranges]

        deltas = [(closes[i] - opens[i]) / ranges[i] * volumes[i]
                  for i in range(len(closes))]

        # Cumulative sum
        cvd = []
        running = 0.0
        for d in deltas:
            running += d
            cvd.append(running)

        window = min(_OBV_WINDOW, len(cvd))
        slope = cvd[-1] - cvd[-window]
        bullish = slope > 0

        return Evidence(
            indicator="cvd",
            value={"cvd_current": round(cvd[-1], 0), "cvd_5bar_slope": round(slope, 0)},
            interpretation=(
                f"CVD 5-bar slope {slope:+,.0f} — "
                f"{'rising (buy pressure)' if bullish else 'falling (sell pressure)'}"
            ),
            weight=0.15,
            bullish=bullish,
        )

    except Exception as exc:
        logger.debug("CVD computation failed: %s", exc)
        return Evidence(
            indicator="cvd",
            value={"error": str(exc)},
            interpretation="CVD unavailable — defaulting neutral/bullish",
            weight=0.15,
            bullish=True,
        )


def compute_vix_evidence(vix_value: float) -> Evidence:
    """
    VIX term structure.

    VIX < 20 → low fear → bullish (favour calls)
    VIX > 25 → high fear → bearish (favour puts or HOLD)
    20–25    → neutral → lean bullish
    """
    if vix_value < _VIX_LOW:
        bullish = True
        interp = f"VIX {vix_value:.1f} < {_VIX_LOW} — low fear, favour calls"
    elif vix_value > _VIX_HIGH:
        bullish = False
        interp = f"VIX {vix_value:.1f} > {_VIX_HIGH} — high fear, favour puts or HOLD"
    else:
        bullish = True  # neutral band — lean bullish
        interp = f"VIX {vix_value:.1f} in neutral band [{_VIX_LOW}–{_VIX_HIGH}] — mildly bullish"

    return Evidence(
        indicator="vix",
        value=round(vix_value, 2),
        interpretation=interp,
        weight=0.15,
        bullish=bullish,
    )


def compute_put_call_evidence(put_call_ratio: float) -> Evidence:
    """
    SPY Put/Call ratio from options chain.

    ratio < 0.7 → bullish (calls dominate)
    ratio > 1.3 → bearish (puts dominate)
    else → neutral → lean bullish
    """
    if put_call_ratio < _PC_BULLISH:
        bullish = True
        interp = f"SPY P/C ratio {put_call_ratio:.2f} < {_PC_BULLISH} — calls dominating, bullish sentiment"
    elif put_call_ratio > _PC_BEARISH:
        bullish = False
        interp = f"SPY P/C ratio {put_call_ratio:.2f} > {_PC_BEARISH} — puts dominating, bearish sentiment"
    else:
        bullish = True
        interp = f"SPY P/C ratio {put_call_ratio:.2f} in neutral zone — no strong bias"

    return Evidence(
        indicator="put_call_ratio",
        value=round(put_call_ratio, 3),
        interpretation=interp,
        weight=0.20,
        bullish=bullish,
    )


def bullish_score_from_evidence(evidence: list[Evidence]) -> float:
    """Weighted fraction of bullish evidence."""
    total = sum(e.weight for e in evidence)
    if total == 0:
        return 0.0
    return sum(e.weight for e in evidence if e.bullish) / total


def nearest_friday(from_date: date | None = None) -> date:
    """Return the nearest upcoming Friday (or today if today is Friday)."""
    today = from_date or datetime.now(tz=timezone.utc).date()
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        return today
    return today + timedelta(days=days_until_friday)


def atm_strike(price: float, rounding: float = 1.0) -> float:
    """Round to nearest dollar (SPY strikes are $1 wide)."""
    return round(price / rounding) * rounding


# ─── TechnicalAnalyst ────────────────────────────────────────────────────────


class TechnicalAnalyst(BaseAnalyst):
    """
    Pure technical analysis analyst for SPY/SPX.

    Wakes every 5 minutes via SCHEDULE trigger. Fetches 5-minute intraday
    bars from yfinance and computes 6 indicators into Evidence items.

    Writes ta_signal.json after every cycle regardless of direction.
    Only emits a TradeSignal when bullish_score >= 0.65 (CALL) or <= 0.35 (PUT).
    """

    _ANALYST_ID = "technical_ta"
    _SOURCE_LAYER = "TECHNICAL"
    _WAKE_INTERVAL = 300  # 5 minutes

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        *,
        confidence_threshold: float = 0.60,
        min_evidence_items: int = 3,
        ta_signal_path: Path = _TA_SIGNAL_PATH,
    ) -> None:
        exit_rules = ExitRules(strategy="TA_RULES")
        super().__init__(
            analyst_id=self._ANALYST_ID,
            source_layer=self._SOURCE_LAYER,
            exit_rules=exit_rules,
            signal_queue=signal_queue,
            wake_trigger="SCHEDULE",
            wake_interval_seconds=self._WAKE_INTERVAL,
            min_evidence_items=min_evidence_items,
            confidence_threshold=confidence_threshold,
        )
        self._ta_signal_path = ta_signal_path

    # ─── Data fetch (override in integration / tests) ─────────────────────

    async def _fetch_spy_bars(self) -> "Any | None":
        """
        Fetch 5-minute SPY bars for today's session via yfinance.
        Returns a DataFrame or None if unavailable.
        """
        try:
            import yfinance as yf
            df = await asyncio.to_thread(
                yf.download, "SPY", period="1d", interval="5m", progress=False, auto_adjust=True
            )
            if df is None or df.empty:
                return None
            # Flatten MultiIndex columns if present (yfinance >= 0.2.x)
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = df.columns.droplevel(1)
            return df
        except Exception as exc:
            self._log.error("Failed to fetch SPY bars: %s", exc)
            return None

    async def _fetch_vix(self) -> float:
        """Fetch latest VIX close from yfinance. Returns 20.0 on failure (neutral)."""
        try:
            import yfinance as yf
            df = await asyncio.to_thread(
                yf.download, "^VIX", period="5d", interval="1d", progress=False, auto_adjust=True
            )
            if df is None or df.empty:
                return 20.0
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = df.columns.droplevel(1)
            return float(df["Close"].iloc[-1])
        except Exception as exc:
            self._log.error("Failed to fetch VIX: %s", exc)
            return 20.0

    async def _fetch_put_call_ratio(self) -> float:
        """
        Approximate SPY put/call ratio from options chain.

        Sums total put volume vs call volume across all expiries.
        Returns 1.0 (neutral) on failure.
        """
        try:
            import yfinance as yf

            def _get_ratio() -> float:
                spy = yf.Ticker("SPY")
                expirations = spy.options
                if not expirations:
                    return 1.0
                total_calls = 0
                total_puts = 0
                # Use first 2 expiries for speed
                for exp in expirations[:2]:
                    try:
                        chain = spy.option_chain(exp)
                        total_calls += int(chain.calls["volume"].fillna(0).sum())
                        total_puts += int(chain.puts["volume"].fillna(0).sum())
                    except Exception:
                        continue
                if total_calls == 0:
                    return 1.0
                return total_puts / total_calls

            return await asyncio.to_thread(_get_ratio)
        except Exception as exc:
            self._log.error("Failed to fetch put/call ratio: %s", exc)
            return 1.0

    # ─── BaseAnalyst abstract methods ─────────────────────────────────────

    async def gather_data(self, trigger: WakeEvent) -> dict | None:
        """
        Fetch SPY bars, VIX, and put/call ratio concurrently.

        Returns a dict with keys: df, vix, put_call_ratio, current_price.
        Returns None if SPY bars are unavailable (skips the cycle).
        """
        df_task = asyncio.create_task(self._fetch_spy_bars())
        vix_task = asyncio.create_task(self._fetch_vix())
        pc_task = asyncio.create_task(self._fetch_put_call_ratio())

        df, vix, put_call = await asyncio.gather(df_task, vix_task, pc_task)

        if df is None or df.empty:
            self._log.warning("No SPY bar data — skipping cycle")
            return None

        current_price = float(df["Close"].iloc[-1])

        return {
            "df": df,
            "vix": vix,
            "put_call_ratio": put_call,
            "current_price": current_price,
        }

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        """
        Compute all 6 indicators and return Evidence items.

        FVG may return None if no gap is nearby — we include it only if found,
        so evidence list may have 5 or 6 items.
        """
        if not isinstance(raw_data, dict):
            return []

        df = raw_data["df"]
        vix = raw_data["vix"]
        put_call = raw_data["put_call_ratio"]
        price = raw_data["current_price"]

        evidence: list[Evidence] = []

        # 1. Fair Value Gap (optional — only if price is in a gap zone)
        fvg = compute_fvg_evidence(df, price)
        if fvg is not None:
            evidence.append(fvg)

        # 2. VWAP
        evidence.append(compute_vwap_evidence(df, price))

        # 3. OBV
        evidence.append(compute_obv_evidence(df))

        # 4. CVD
        evidence.append(compute_cvd_evidence(df))

        # 5. VIX
        evidence.append(compute_vix_evidence(vix))

        # 6. Put/Call ratio
        evidence.append(compute_put_call_evidence(put_call))

        return evidence

    async def select_contract(
        self,
        evidence: list[Evidence],
        raw_data: Any,
    ) -> OptionContract | None:
        """
        Decide direction and write ta_signal.json.

        Returns None for HOLD (score in 0.35–0.65 band).
        Also writes ta_signal.json before returning — always, even on HOLD.
        """
        score = bullish_score_from_evidence(evidence)
        price: float = raw_data.get("current_price", 0.0) if isinstance(raw_data, dict) else 0.0
        vix: float = raw_data.get("vix", 20.0) if isinstance(raw_data, dict) else 20.0
        put_call: float = raw_data.get("put_call_ratio", 1.0) if isinstance(raw_data, dict) else 1.0

        # Build raw indicators for the TA signal file
        indicators: dict[str, Any] = {
            "spy_price": round(price, 2),
            "vix": round(vix, 2),
            "put_call_ratio": round(put_call, 3),
            "indicators_detail": [
                {"indicator": e.indicator, "value": e.value,
                 "bullish": e.bullish, "weight": e.weight}
                for e in evidence
            ],
        }

        # Determine direction
        if score >= _BULLISH_THRESHOLD:
            direction: str = "CALL"
        elif score <= _BEARISH_THRESHOLD:
            direction = "PUT"
        else:
            direction = "HOLD"

        # Write TA signal file — always, every cycle
        ta_signal = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "symbol": "SPY",
            "direction": direction,
            "confidence": round(score, 4),
            "bullish_score": round(score, 4),
            "evidence_count": len(evidence),
            "indicators": indicators,
        }
        try:
            atomic_write_json(self._ta_signal_path, ta_signal)
        except Exception as exc:
            self._log.error("Failed to write ta_signal.json: %s", exc)

        # HOLD — no signal
        if direction == "HOLD":
            self._log.info(
                "TA score %.2f in HOLD band [%.2f, %.2f] — no signal emitted",
                score, _BEARISH_THRESHOLD, _BULLISH_THRESHOLD,
            )
            return None

        # Select ATM contract
        if price <= 0:
            self._log.warning("SPY price unavailable — cannot select contract")
            return None

        strike = atm_strike(price)
        expiry = nearest_friday()

        # Estimate ATM option price (~0.5% of SPY price)
        estimated_mark = max(round(price * 0.005, 2), 0.10)

        self._log.info(
            "TA signal: %s SPY %.0f exp=%s score=%.2f ev=%d",
            direction, strike, expiry, score, len(evidence),
        )

        return OptionContract(
            symbol="SPY",
            direction=direction,  # type: ignore[arg-type]
            strike=strike,
            expiry=expiry,
            bid_per_share=round(estimated_mark * 0.95, 2),
            ask_per_share=round(estimated_mark * 1.05, 2),
            mark_per_share=estimated_mark,
            open_interest=0,
            volume=0,
        )

    # ─── Public API for MonitorAgent ──────────────────────────────────────

    async def get_current_signal(self) -> dict:
        """
        Read and return the current ta_signal.json.

        Used by MonitorAgent for TA_RULES exit decisions.
        Returns empty dict if file is missing or malformed.
        """
        try:
            text = self._ta_signal_path.read_text(encoding="utf-8")
            return json.loads(text)
        except FileNotFoundError:
            self._log.debug("ta_signal.json not found")
            return {}
        except json.JSONDecodeError as exc:
            self._log.error("ta_signal.json malformed: %s", exc)
            return {}

    def compute_confidence(self, evidence: list[Evidence]) -> float:
        """
        Confidence = distance from 0.5 centre, scaled to [0, 1].
        Decisively bullish or bearish is high confidence.
        """
        score = bullish_score_from_evidence(evidence)
        return abs(score - 0.5) * 2

    def _infer_direction(self, evidence: list[Evidence]) -> OptionDirection:
        score = bullish_score_from_evidence(evidence)
        return "CALL" if score >= 0.5 else "PUT"

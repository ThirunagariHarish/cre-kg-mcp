"""
analysts/unusual_whales/spy_spx.py — SPY/SPX Unusual Whales Analyst (M3.3).

Reads market-wide UW signals every 5 minutes during RTH and emits a CALL or PUT
signal on SPY when the weighted evidence score is decisive enough.

Indicators (each becomes one Evidence item):
  1. Call/Put ratio     weight=0.25  — >1.2 bullish, <0.8 bearish
  2. GEX               weight=0.20  — positive supports current direction
  3. UW call volume    weight=0.30  — >3× 20-day avg is directional
  4. VIX               weight=0.15  — <20 → low fear → favour calls
  5. SPY vs VWAP       weight=0.10  — above VWAP bullish, below bearish

Decision thresholds:
  bullish_score >= 0.60  → CALL on SPY ATM nearest-Friday expiry
  bullish_score <= 0.40  → PUT  on SPY ATM nearest-Friday expiry
  0.40 < score < 0.60    → no signal (uncertain)

Exit: TA_RULES — Technical Analyst calls the exit.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from core.base_analyst import BaseAnalyst, WakeEvent
from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    OptionDirection,
    TradeSignal,
)

logger = logging.getLogger("analyst.spy_spx_uw")

# ─── Decision thresholds ──────────────────────────────────────────────────────

_BULLISH_THRESHOLD = 0.60
_BEARISH_THRESHOLD = 0.40

# ─── Indicator thresholds ─────────────────────────────────────────────────────

_CALL_PUT_BULLISH = 1.2
_CALL_PUT_BEARISH = 0.8
_VOLUME_MULTIPLIER = 3.0   # unusual = >3× 20-day avg
_VIX_LOW_FEAR = 20.0


# ─── Pure helpers (testable without asyncio) ──────────────────────────────────

def build_evidence_from_market_data(data: dict) -> list[Evidence]:
    """
    Convert a market-data snapshot dict into Evidence items.

    Expected keys in `data`:
      call_put_ratio: float
      gex: float                  — Gamma Exposure (positive = dealers long gamma)
      spy_call_volume: float      — today's SPY call volume
      spy_call_volume_avg_20d: float
      vix: float
      spy_price: float
      spy_vwap: float
    """
    evidence: list[Evidence] = []

    # 1. Call/Put ratio (weight=0.25)
    cp_ratio: float = data.get("call_put_ratio", 1.0)
    if cp_ratio > _CALL_PUT_BULLISH:
        cp_bullish = True
        cp_interp = f"Call/Put ratio {cp_ratio:.2f} > {_CALL_PUT_BULLISH} — bullish flow dominates"
    elif cp_ratio < _CALL_PUT_BEARISH:
        cp_bullish = False
        cp_interp = f"Call/Put ratio {cp_ratio:.2f} < {_CALL_PUT_BEARISH} — put flow dominates"
    else:
        # Neutral — treat as mildly bullish (markets drift up)
        cp_bullish = True
        cp_interp = f"Call/Put ratio {cp_ratio:.2f} — neutral, no strong bias"
    evidence.append(Evidence(
        indicator="call_put_ratio",
        value=cp_ratio,
        interpretation=cp_interp,
        weight=0.25,
        bullish=cp_bullish,
    ))

    # 2. GEX — Gamma Exposure (weight=0.20)
    gex: float = data.get("gex", 0.0)
    # Positive GEX means dealers are long gamma — they buy dips, sell rips → dampens vol
    # Negative GEX → dealers short gamma → amplifies moves
    # For our purposes: positive GEX supports whichever direction the other indicators favour.
    # We encode it as bullish=True when positive (supports established trend),
    # bullish=False when deeply negative (chaotic, increases risk).
    gex_bullish = gex >= 0
    gex_interp = (
        f"GEX {gex:+,.0f} — {'positive (stable, supports trend)' if gex_bullish else 'negative (unstable, amplifies moves)'}"
    )
    evidence.append(Evidence(
        indicator="gex",
        value=gex,
        interpretation=gex_interp,
        weight=0.20,
        bullish=gex_bullish,
    ))

    # 3. Unusual SPY/SPX call volume (weight=0.30)
    call_vol: float = data.get("spy_call_volume", 0.0)
    avg_20d: float = data.get("spy_call_volume_avg_20d", 1.0) or 1.0  # guard /0
    vol_ratio = call_vol / avg_20d
    vol_unusual = vol_ratio >= _VOLUME_MULTIPLIER
    vol_bullish = vol_unusual  # unusual call flow is bullish for SPY
    vol_interp = (
        f"SPY call volume {call_vol:,.0f} is {vol_ratio:.1f}× 20-day avg — "
        f"{'unusual (bullish flow)' if vol_unusual else 'normal (no edge)'}"
    )
    evidence.append(Evidence(
        indicator="uw_call_volume",
        value=vol_ratio,
        interpretation=vol_interp,
        weight=0.30,
        bullish=vol_bullish,
    ))

    # 4. VIX (weight=0.15)
    vix: float = data.get("vix", 20.0)
    vix_bullish = vix < _VIX_LOW_FEAR
    vix_interp = (
        f"VIX {vix:.1f} — {'low fear, favour calls' if vix_bullish else 'elevated fear, caution on calls'}"
    )
    evidence.append(Evidence(
        indicator="vix",
        value=vix,
        interpretation=vix_interp,
        weight=0.15,
        bullish=vix_bullish,
    ))

    # 5. SPY price vs VWAP (weight=0.10)
    spy_price: float = data.get("spy_price", 0.0)
    spy_vwap: float = data.get("spy_vwap", 0.0)
    if spy_vwap > 0:
        above_vwap = spy_price >= spy_vwap
        vwap_interp = (
            f"SPY ${spy_price:.2f} {'above' if above_vwap else 'below'} VWAP ${spy_vwap:.2f} — "
            f"{'bullish momentum' if above_vwap else 'bearish momentum'}"
        )
    else:
        above_vwap = True  # fallback if no VWAP data
        vwap_interp = "VWAP not available — defaulting to neutral/bullish"
    evidence.append(Evidence(
        indicator="spy_vs_vwap",
        value=spy_price,
        interpretation=vwap_interp,
        weight=0.10,
        bullish=above_vwap,
    ))

    return evidence


def bullish_score_from_evidence(evidence: list[Evidence]) -> float:
    """Weighted fraction of bullish evidence."""
    total = sum(e.weight for e in evidence)
    if total == 0:
        return 0.0
    return sum(e.weight for e in evidence if e.bullish) / total


def nearest_friday(from_date: date | None = None) -> date:
    """Return the nearest upcoming Friday (or today if today is Friday)."""
    today = from_date or datetime.now(tz=timezone.utc).date()
    days_until_friday = (4 - today.weekday()) % 7  # Friday=4
    if days_until_friday == 0:
        return today
    return today + timedelta(days=days_until_friday)


def atm_strike(spy_price: float, rounding: float = 1.0) -> float:
    """Round spy_price to nearest dollar (SPY strikes are $1 wide)."""
    return round(spy_price / rounding) * rounding


# ─── SPYSPXUWAnalyst ──────────────────────────────────────────────────────────

class SPYSPXUWAnalyst(BaseAnalyst):
    """
    Market-wide Unusual Whales analyst for SPY/SPX options.

    Wakes every 5 minutes via SCHEDULE trigger. Calls gather_data() which is
    expected to return a market snapshot dict from the UW data source.
    Subclasses or integration harnesses can monkey-patch _fetch_market_data()
    to plug in real or mock data.
    """

    # Class-level defaults — match the spec
    _ANALYST_ID = "spy_spx_uw"
    _SOURCE_LAYER = "UNUSUAL_WHALES"
    _WAKE_INTERVAL = 300  # 5 min

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        *,
        confidence_threshold: float = 0.60,
        min_evidence_items: int = 3,
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

    # ─── Data fetch (override in integration for real UW client) ──────────

    async def _fetch_market_data(self) -> dict | None:
        """
        Fetch a market snapshot from the Unusual Whales API.

        Returns a dict with keys:
          call_put_ratio, gex, spy_call_volume, spy_call_volume_avg_20d,
          vix, spy_price, spy_vwap

        Returns None if data is unavailable (skips the cycle).

        In production, replace this with actual UW API calls via httpx.
        In tests, patch this method on the instance.
        """
        # Placeholder — real implementation calls UW REST endpoints
        self._log.debug("_fetch_market_data: no real UW client wired up — returning None")
        return None

    # ─── BaseAnalyst abstract methods ─────────────────────────────────────

    async def gather_data(self, trigger: WakeEvent) -> Any:
        """Fetch market snapshot. Returns dict or None."""
        return await self._fetch_market_data()

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        """Convert market snapshot into Evidence items."""
        if not isinstance(raw_data, dict):
            return []
        return build_evidence_from_market_data(raw_data)

    async def select_contract(
        self,
        evidence: list[Evidence],
        raw_data: Any,
    ) -> OptionContract | None:
        """
        Decide direction from evidence, then select ATM SPY option.
        Returns None if evidence is uncertain (0.40 < score < 0.60).
        """
        score = bullish_score_from_evidence(evidence)

        if score >= _BULLISH_THRESHOLD:
            direction: OptionDirection = "CALL"
        elif score <= _BEARISH_THRESHOLD:
            direction = "PUT"
        else:
            self._log.info(
                "Score %.2f is in uncertain band [%.2f, %.2f] — no signal",
                score, _BEARISH_THRESHOLD, _BULLISH_THRESHOLD,
            )
            return None

        spy_price: float = raw_data.get("spy_price", 0.0) if isinstance(raw_data, dict) else 0.0
        if spy_price <= 0:
            self._log.warning("spy_price not available — cannot select contract")
            return None

        strike = atm_strike(spy_price)
        expiry = nearest_friday()

        # Estimated option price: 0.5% of SPY price (rough ATM estimate)
        estimated_mark = round(spy_price * 0.005, 2)
        estimated_mark = max(estimated_mark, 0.10)  # minimum $0.10

        return OptionContract(
            symbol="SPY",
            direction=direction,
            strike=strike,
            expiry=expiry,
            bid_per_share=round(estimated_mark * 0.95, 2),
            ask_per_share=round(estimated_mark * 1.05, 2),
            mark_per_share=estimated_mark,
            open_interest=0,
            volume=0,
        )

    def compute_confidence(self, evidence: list[Evidence]) -> float:
        """Confidence equals the bullish (or bearish) score magnitude."""
        score = bullish_score_from_evidence(evidence)
        # Distance from 0.5 centre — decisively bullish or bearish is high confidence
        return abs(score - 0.5) * 2  # maps [0.5, 1.0] → [0.0, 1.0]

    def _infer_direction(self, evidence: list[Evidence]) -> OptionDirection:
        score = bullish_score_from_evidence(evidence)
        return "CALL" if score >= 0.5 else "PUT"

"""
analysts/unusual_whales/screener.py — Options Screener Analyst (M3.4).

Scans the Unusual Whales options screener every 5 minutes and emits trade
signals for the top-3 unusual-volume candidates that pass all filters.

Screening criteria (each becomes an Evidence item):
  1. Options volume > 3× 20-day avg OI     weight=0.35  (primary filter)
  2. Market cap > $2B AND float > 10M      weight=0.20
  3. Beta 0.8 ≤ β ≤ 3.0                   weight=0.15
  4. Price NOT near 52-week high/low       weight=0.20  (±5% band)
  5. Earnings > 14 days away              weight=0.10

Candidate selection:
  - Apply all criteria
  - Sort by unusual_volume_ratio descending
  - Take top 3

Exit: TA_RULES — Technical Analyst handles exit.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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

logger = logging.getLogger("analyst.screener")

# ─── Filter thresholds ────────────────────────────────────────────────────────

_VOLUME_RATIO_MIN = 3.0         # options volume must be 3× avg OI
_MARKET_CAP_MIN_B = 2.0         # $2B minimum
_FLOAT_MIN_M = 10.0             # 10M shares minimum float
_BETA_MIN = 0.8
_BETA_MAX = 3.0
_NEAR_52W_BAND = 0.05           # ±5% of 52w high/low is "near" — avoid chasing
_EARNINGS_MIN_DAYS = 14         # earnings must be > 14 days out
_TOP_N = 3                      # number of candidates to emit


# ─── Candidate dataclass ─────────────────────────────────────────────────────

@dataclass
class ScreenerCandidate:
    """One row returned by the UW screener endpoint."""
    symbol: str
    direction: OptionDirection       # dominant flow direction (CALL or PUT)
    strike: float
    expiry: date
    current_price: float
    option_volume: float             # today's option volume
    avg_oi_20d: float               # 20-day average open interest
    market_cap_b: float             # market cap in billions
    float_m: float                  # float in millions of shares
    beta: float
    price_52w_high: float
    price_52w_low: float
    earnings_date: date | None       # None if unknown / far future
    unusual_volume_ratio: float      # pre-computed vol / avg_oi_20d


# ─── Pure helpers (testable without asyncio) ──────────────────────────────────

def build_candidate_evidence(c: ScreenerCandidate) -> list[Evidence]:
    """
    Build one Evidence item per screening criterion for a single candidate.

    All five criteria are always included (even failures) so the Master Analyst
    can see the full picture. The bullish field encodes pass/fail.
    """
    evidence: list[Evidence] = []

    # 1. Volume ratio (weight=0.35)
    vol_pass = c.unusual_volume_ratio >= _VOLUME_RATIO_MIN
    evidence.append(Evidence(
        indicator="uw_volume_ratio",
        value=c.unusual_volume_ratio,
        interpretation=(
            f"{c.symbol} option volume is {c.unusual_volume_ratio:.1f}× 20-day avg OI — "
            f"{'unusual flow detected' if vol_pass else 'normal volume, no edge'}"
        ),
        weight=0.35,
        bullish=vol_pass,
    ))

    # 2. Market cap + float (weight=0.20)
    cap_pass = c.market_cap_b >= _MARKET_CAP_MIN_B and c.float_m >= _FLOAT_MIN_M
    evidence.append(Evidence(
        indicator="liquidity_filter",
        value={"market_cap_b": c.market_cap_b, "float_m": c.float_m},
        interpretation=(
            f"Market cap ${c.market_cap_b:.1f}B, float {c.float_m:.0f}M shares — "
            f"{'sufficient liquidity' if cap_pass else 'insufficient liquidity'}"
        ),
        weight=0.20,
        bullish=cap_pass,
    ))

    # 3. Beta filter (weight=0.15)
    beta_pass = _BETA_MIN <= c.beta <= _BETA_MAX
    evidence.append(Evidence(
        indicator="beta_filter",
        value=c.beta,
        interpretation=(
            f"Beta {c.beta:.2f} — "
            f"{'within tradable range [{_BETA_MIN}, {_BETA_MAX}]' if beta_pass else 'outside tradable range'}"
        ),
        weight=0.15,
        bullish=beta_pass,
    ))

    # 4. Not near 52-week high/low (weight=0.20)
    high_band = c.price_52w_high * (1 - _NEAR_52W_BAND)
    low_band = c.price_52w_low * (1 + _NEAR_52W_BAND)
    not_near_extremes = low_band < c.current_price < high_band
    evidence.append(Evidence(
        indicator="price_extremes",
        value={
            "current": c.current_price,
            "52w_high": c.price_52w_high,
            "52w_low": c.price_52w_low,
        },
        interpretation=(
            f"${c.current_price:.2f} is "
            f"{'NOT near 52w extremes (safe to trade)' if not_near_extremes else 'near 52w high/low — avoid breakout chasing'}"
        ),
        weight=0.20,
        bullish=not_near_extremes,
    ))

    # 5. Earnings check (weight=0.10)
    today = datetime.now(tz=timezone.utc).date()
    if c.earnings_date is None:
        earnings_safe = True
        earnings_interp = "No earnings date known — treating as safe"
    else:
        days_to_earnings = (c.earnings_date - today).days
        earnings_safe = days_to_earnings > _EARNINGS_MIN_DAYS
        earnings_interp = (
            f"Earnings in {days_to_earnings} days ({c.earnings_date}) — "
            f"{'safe window' if earnings_safe else 'too close, avoid earnings risk'}"
        )
    evidence.append(Evidence(
        indicator="earnings_check",
        value=str(c.earnings_date) if c.earnings_date else None,
        interpretation=earnings_interp,
        weight=0.10,
        bullish=earnings_safe,
    ))

    return evidence


def passes_all_criteria(evidence: list[Evidence]) -> bool:
    """Return True only if every criterion passes (all bullish=True)."""
    return all(e.bullish for e in evidence)


def filter_and_rank(
    candidates: list[ScreenerCandidate],
) -> list[tuple[ScreenerCandidate, list[Evidence]]]:
    """
    Apply all screening criteria, filter to passing candidates only,
    sort by unusual_volume_ratio descending, return top _TOP_N.
    """
    results: list[tuple[ScreenerCandidate, list[Evidence]]] = []
    for c in candidates:
        ev = build_candidate_evidence(c)
        if passes_all_criteria(ev):
            results.append((c, ev))

    results.sort(key=lambda x: x[0].unusual_volume_ratio, reverse=True)
    return results[:_TOP_N]


# ─── ScreenerAnalyst ──────────────────────────────────────────────────────────

class ScreenerAnalyst(BaseAnalyst):
    """
    Options screener analyst that emits signals for top unusual-volume candidates.

    Emits up to _TOP_N (3) TradeSignals per wake cycle — one per candidate.
    Each signal is independently deduplicated.
    """

    _ANALYST_ID = "screener"
    _SOURCE_LAYER = "SCREENER"
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

    async def _fetch_screener_data(self) -> list[ScreenerCandidate]:
        """
        Fetch candidates from the UW options screener.

        Returns a list of ScreenerCandidate objects.
        Returns [] if data is unavailable.

        In production, replace with real UW API calls.
        In tests, patch this method on the instance.
        """
        self._log.debug("_fetch_screener_data: no real UW client wired up — returning []")
        return []

    # ─── BaseAnalyst abstract methods ─────────────────────────────────────
    #
    # NOTE: The screener emits MULTIPLE signals per cycle (one per top candidate).
    # BaseAnalyst._process() handles one signal. We override _process() to loop
    # over all top candidates and emit a signal for each.

    async def gather_data(self, trigger: WakeEvent) -> Any:
        """Fetch and filter screener candidates. Returns top list."""
        raw_candidates = await self._fetch_screener_data()
        return filter_and_rank(raw_candidates)

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        """
        Not directly used — ScreenerAnalyst._process() calls build_candidate_evidence()
        per candidate instead of calling this method. Return [] to satisfy the ABC.
        This method is only called by BaseAnalyst._process() which we override.
        """
        return []

    async def select_contract(
        self,
        evidence: list[Evidence],
        raw_data: Any,
    ) -> OptionContract | None:
        """Not used — _process() is fully overridden."""
        return None

    async def _process(self, trigger: WakeEvent) -> None:
        """
        Override BaseAnalyst._process() to emit one signal per top candidate.
        """
        from core.kill_switch import is_blocked
        from core.logging import TradeEvent, journal

        if is_blocked():
            self._log.warning("Kill switch active — skipping screener cycle")
            journal(TradeEvent.KILL_SWITCH_BLOCKED, self.analyst_id, "none",
                    extra={"trigger": trigger.trigger})
            return

        # gather_data returns list[tuple[ScreenerCandidate, list[Evidence]]]
        try:
            top_candidates: list[tuple[ScreenerCandidate, list[Evidence]]] = (
                await self.gather_data(trigger)
            )
        except Exception as exc:
            self._log.error("gather_data failed: %s", exc)
            return

        if not top_candidates:
            self._log.debug("No candidates passed screening — skipping cycle")
            return

        now = datetime.now(tz=timezone.utc)

        for candidate, evidence in top_candidates:
            # Confidence = fraction of evidence that is bullish (all should pass here)
            confidence = self.compute_confidence(evidence)

            # Dedup: same symbol + direction + expiry from screener within 5 min
            dedup_key = (
                f"{self.analyst_id}:{candidate.symbol}:{candidate.direction}:{candidate.expiry}"
            )
            if dedup_key in self._seen_signal_keys:
                self._log.info("Duplicate screener signal suppressed: %s", dedup_key)
                continue

            # Contract
            estimated_mark = round(candidate.current_price * 0.01, 2)  # ~1% of stock price
            estimated_mark = max(estimated_mark, 0.10)

            contract = OptionContract(
                symbol=candidate.symbol,
                direction=candidate.direction,
                strike=candidate.strike,
                expiry=candidate.expiry,
                bid_per_share=round(estimated_mark * 0.95, 2),
                ask_per_share=round(estimated_mark * 1.05, 2),
                mark_per_share=estimated_mark,
                open_interest=int(candidate.avg_oi_20d),
                volume=int(candidate.option_volume),
            )

            signal = TradeSignal(
                analyst_id=self.analyst_id,
                source_layer=self.source_layer,
                timestamp=now,
                symbol=candidate.symbol,
                direction=candidate.direction,
                strike=candidate.strike,
                expiry=candidate.expiry,
                signal_price=estimated_mark,
                evidence=evidence,
                risk_level=self.compute_risk_level(evidence),
                confidence=confidence,
                exit_rules=self.exit_rules,
                source_metadata={
                    "unusual_volume_ratio": candidate.unusual_volume_ratio,
                    "market_cap_b": candidate.market_cap_b,
                    "beta": candidate.beta,
                    "earnings_date": str(candidate.earnings_date) if candidate.earnings_date else None,
                },
            )

            self._seen_signal_keys.add(dedup_key)
            import asyncio as _asyncio
            _asyncio.create_task(self._clear_dedup(dedup_key, delay=300))

            await self.signal_queue.put(signal)
            journal(
                TradeEvent.SIGNAL_EMITTED,
                self.analyst_id,
                signal.signal_id,
                extra={
                    "symbol": signal.symbol,
                    "direction": signal.direction,
                    "strike": signal.strike,
                    "expiry": str(signal.expiry),
                    "confidence": signal.confidence,
                    "unusual_volume_ratio": candidate.unusual_volume_ratio,
                },
            )
            self._log.info(
                "Screener signal emitted: %s %s %.1f exp=%s vol_ratio=%.1f conf=%.2f",
                signal.symbol, signal.direction, signal.strike,
                signal.expiry, candidate.unusual_volume_ratio, confidence,
            )

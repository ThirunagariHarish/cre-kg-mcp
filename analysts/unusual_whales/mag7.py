"""
analysts/unusual_whales/mag7.py — Magnificent 7 weekly calls analyst.

Tracks AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA for unusual options flow
and momentum-based weekly call opportunities.

Wake: every 15 minutes during RTH (9:30 AM – 4:00 PM ET, Mon–Fri).

Scoring evidence (must have 3+ bullish items to emit):
  1. UW option flow: premium > $100k on weekly calls     (weight=0.30)
  2. Price momentum: 5-day return > 2%                   (weight=0.25)
  3. Volume vs 20-day avg: > 1.5×                        (weight=0.20)
  4. Sector strength: XLK vs SPY return                  (weight=0.15)
  5. RSI < 70 (not overbought)                           (weight=0.10)

Exit: PRICE_TARGET at 1.05× entry.
Expiry: nearest weekly Friday.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.base_analyst import BaseAnalyst, WakeEvent
from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    TradeSignal,
)

logger = logging.getLogger("analyst.mag7")

_WATCHLIST_PATH = Path("configs/analysts/mag7_watchlist.json")
_DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]

# RTH window in ET (UTC-4 in summer, UTC-5 in winter — we use a fixed offset)
_RTH_OPEN_HOUR_ET = 9
_RTH_OPEN_MINUTE_ET = 30
_RTH_CLOSE_HOUR_ET = 16

# UW flow threshold for "unusual" premium
_UW_MIN_PREMIUM = 100_000

# Momentum threshold: 5-day return > 2%
_MOMENTUM_THRESHOLD = 0.02

# Volume multiple: > 1.5× 20-day avg
_VOLUME_MULTIPLE = 1.5

# RSI threshold: not overbought
_RSI_OVERBOUGHT = 70.0

# Sector ETF for tech
_TECH_ETF = "XLK"
_MARKET_ETF = "SPY"


def _load_watchlist() -> list[str]:
    """Load watchlist from config file, falling back to defaults."""
    try:
        data = json.loads(_WATCHLIST_PATH.read_text(encoding="utf-8"))
        return data.get("watchlist", _DEFAULT_WATCHLIST)
    except Exception as exc:
        logger.warning("Could not load mag7 watchlist from %s: %s — using defaults", _WATCHLIST_PATH, exc)
        return _DEFAULT_WATCHLIST


def _nearest_weekly_friday(from_date: date | None = None) -> date:
    """Return the nearest upcoming Friday (inclusive of today if today is Friday)."""
    today = from_date or datetime.now(tz=timezone.utc).date()
    days_ahead = (4 - today.weekday()) % 7  # 4 = Friday
    if days_ahead == 0:
        return today
    return today + timedelta(days=days_ahead)


def _is_rth(dt: datetime | None = None) -> bool:
    """
    Returns True if the given UTC datetime falls within RTH (9:30–16:00 ET, Mon–Fri).
    Uses UTC-4 as a fixed ET offset (covers EDT; during EST the window shifts by 1 hour
    but this is an acceptable approximation for a scheduled analyst).
    """
    dt = dt or datetime.now(tz=timezone.utc)
    et_offset = timedelta(hours=-4)
    et_time = dt + et_offset
    if et_time.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    rth_start = et_time.replace(hour=_RTH_OPEN_HOUR_ET, minute=_RTH_OPEN_MINUTE_ET, second=0)
    rth_end = et_time.replace(hour=_RTH_CLOSE_HOUR_ET, minute=0, second=0)
    return rth_start <= et_time < rth_end


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Simple RSI calculation from a list of closing prices."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    if not gains and not losses:
        return 50.0
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class Mag7Analyst(BaseAnalyst):
    """
    Magnificent 7 weekly calls analyst.

    Wakes every 15 minutes during RTH and scores each Mag7 symbol across
    5 evidence dimensions. Emits a CALL TradeSignal when 3+ items are bullish
    and confidence exceeds threshold.
    """

    analyst_id = "mag7"
    source_layer = "UNUSUAL_WHALES"
    wake_trigger = "SCHEDULE"
    wake_interval_seconds = 900  # 15 min

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        uw_client: Any,  # UWClient instance — injected for testability
        *,
        confidence_threshold: float = 0.65,
        min_evidence_items: int = 3,
    ) -> None:
        exit_rules = ExitRules(
            strategy="PRICE_TARGET",
            price_target_multiplier=1.05,
        )
        super().__init__(
            analyst_id=self.analyst_id,
            source_layer=self.source_layer,
            exit_rules=exit_rules,
            signal_queue=signal_queue,
            wake_trigger=self.wake_trigger,
            wake_interval_seconds=self.wake_interval_seconds,
            min_evidence_items=min_evidence_items,
            confidence_threshold=confidence_threshold,
        )
        self._uw = uw_client
        self._watchlist = _load_watchlist()

    # ─── BaseAnalyst abstract methods ─────────────────────────────────────

    async def gather_data(self, trigger: WakeEvent) -> Any:
        """
        Return a dict of symbol → raw market data if we're in RTH,
        else return None to skip the cycle.
        """
        if not _is_rth():
            self._log.debug("Outside RTH — skipping cycle")
            return None

        result: dict[str, dict] = {}
        for symbol in self._watchlist:
            try:
                flow = await self._uw.get_option_flow(symbol)
                prices, volumes = await self._fetch_price_volume(symbol)
                sector_ret = await self._fetch_sector_relative_return()
                result[symbol] = {
                    "flow": flow,
                    "prices": prices,
                    "volumes": volumes,
                    "sector_ret": sector_ret,
                }
            except Exception as exc:
                logger.warning("Failed to gather data for %s: %s", symbol, exc)

        return result if result else None

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        """
        Score all symbols and return the evidence list for the best candidate.
        Only returns evidence for a symbol if 3+ items are bullish.
        Returns [] if no symbol qualifies.
        """
        if not isinstance(raw_data, dict):
            return []

        best: tuple[float, list[Evidence], str] | None = None

        for symbol, data in raw_data.items():
            evidence = self._score_symbol(symbol, data)
            bullish_count = sum(1 for e in evidence if e.bullish)
            if bullish_count < self.min_evidence_items:
                continue
            score = sum(e.weight for e in evidence if e.bullish)
            if best is None or score > best[0]:
                best = (score, evidence, symbol)

        if best is None:
            return []
        return best[1]

    async def select_contract(
        self,
        evidence: list[Evidence],
        raw_data: Any,
    ) -> OptionContract | None:
        """
        Select the nearest weekly Friday call for the best-scoring symbol.
        Derives a reasonable mark price from the UW flow data.
        """
        if not evidence:
            return None

        # Identify which symbol's evidence we're working with
        symbol = self._extract_symbol_from_evidence(evidence)
        if not symbol or not isinstance(raw_data, dict):
            return None

        data = raw_data.get(symbol)
        if not data:
            return None

        prices = data.get("prices", [])
        if not prices:
            return None

        stock_price = prices[-1]
        # Round strike to nearest $5 for a realistic ATM/slight-OTM weekly call
        strike = round(stock_price / 5.0) * 5.0

        # Estimate a rough mark price (2-3% of stock price for a near-the-money weekly)
        estimated_mark = max(0.50, round(stock_price * 0.025, 2))
        bid = round(estimated_mark * 0.95, 2)
        ask = round(estimated_mark * 1.05, 2)

        # Ensure ask >= 0.10 (minimum tradable)
        if ask < 0.10:
            ask = 0.10
            bid = 0.09

        expiry = _nearest_weekly_friday()

        return OptionContract(
            symbol=symbol,
            direction="CALL",
            strike=strike,
            expiry=expiry,
            bid_per_share=bid,
            ask_per_share=ask,
            mark_per_share=estimated_mark,
            open_interest=0,
            volume=0,
        )

    # ─── Scoring helpers ──────────────────────────────────────────────────

    def _score_symbol(self, symbol: str, data: dict) -> list[Evidence]:
        """Build the 5 evidence items for a single symbol."""
        evidence: list[Evidence] = []

        # 1. UW unusual options flow: premium > $100k on weekly calls
        flow = data.get("flow", [])
        max_premium = 0.0
        for record in flow:
            try:
                p = float(record.get("premium", 0) or 0)
                direction = str(record.get("call_or_put", record.get("type", "")) or "").upper()
                if "CALL" in direction or "C" == direction:
                    max_premium = max(max_premium, p)
            except (TypeError, ValueError):
                continue

        evidence.append(Evidence(
            indicator="uw_option_flow",
            value=max_premium,
            interpretation=(
                f"UW weekly call flow max premium ${max_premium:,.0f} "
                f"({'above' if max_premium >= _UW_MIN_PREMIUM else 'below'} $100k threshold)"
            ),
            weight=0.30,
            bullish=max_premium >= _UW_MIN_PREMIUM,
        ))

        # 2. Price momentum: 5-day return > 2%
        prices = data.get("prices", [])
        momentum = None
        if len(prices) >= 6:
            momentum = (prices[-1] - prices[-6]) / prices[-6]
        elif len(prices) >= 2:
            momentum = (prices[-1] - prices[0]) / prices[0]

        evidence.append(Evidence(
            indicator="price_momentum_5d",
            value=round(momentum * 100, 2) if momentum is not None else None,
            interpretation=(
                f"5-day return {momentum * 100:.1f}% ({'above' if momentum and momentum >= _MOMENTUM_THRESHOLD else 'below'} 2% threshold)"
                if momentum is not None else "Insufficient price history for momentum"
            ),
            weight=0.25,
            bullish=(momentum is not None and momentum >= _MOMENTUM_THRESHOLD),
        ))

        # 3. Volume vs 20-day avg: > 1.5×
        volumes = data.get("volumes", [])
        vol_multiple = None
        if len(volumes) >= 20 and volumes[-1]:
            avg_vol = sum(volumes[-21:-1]) / 20.0
            if avg_vol > 0:
                vol_multiple = volumes[-1] / avg_vol

        evidence.append(Evidence(
            indicator="volume_vs_20d_avg",
            value=round(vol_multiple, 2) if vol_multiple is not None else None,
            interpretation=(
                f"Volume {vol_multiple:.2f}× 20-day avg ({'above' if vol_multiple and vol_multiple >= _VOLUME_MULTIPLE else 'below'} 1.5× threshold)"
                if vol_multiple is not None else "Insufficient volume history"
            ),
            weight=0.20,
            bullish=(vol_multiple is not None and vol_multiple >= _VOLUME_MULTIPLE),
        ))

        # 4. Sector strength: XLK vs SPY return (positive = tech outperforming)
        sector_ret = data.get("sector_ret")
        evidence.append(Evidence(
            indicator="sector_strength",
            value=round(sector_ret * 100, 2) if sector_ret is not None else None,
            interpretation=(
                f"XLK vs SPY relative return {sector_ret * 100:+.2f}% ({'outperforming' if sector_ret and sector_ret > 0 else 'underperforming'})"
                if sector_ret is not None else "Sector data unavailable"
            ),
            weight=0.15,
            bullish=(sector_ret is not None and sector_ret > 0),
        ))

        # 5. RSI < 70 (not overbought)
        rsi = _compute_rsi(prices) if prices else None
        evidence.append(Evidence(
            indicator="rsi_not_overbought",
            value=round(rsi, 1) if rsi is not None else None,
            interpretation=(
                f"RSI {rsi:.1f} ({'not overbought' if rsi and rsi < _RSI_OVERBOUGHT else 'overbought'})"
                if rsi is not None else "Insufficient data for RSI"
            ),
            weight=0.10,
            bullish=(rsi is not None and rsi < _RSI_OVERBOUGHT),
        ))

        return evidence

    def _extract_symbol_from_evidence(self, evidence: list[Evidence]) -> str | None:
        """
        Extract the symbol from the source_metadata of the evidence.
        Since evidence items don't carry the symbol directly, we use raw_data lookup.
        This method is a hook that the caller can override by passing symbol directly.
        Returns None — caller (select_contract) must handle via raw_data.
        """
        # Evidence items don't carry symbol — the caller passes raw_data alongside.
        # We return None here; select_contract iterates raw_data to find the best match.
        return None

    async def select_contract(
        self,
        evidence: list[Evidence],
        raw_data: Any,
    ) -> OptionContract | None:
        """
        Identify the best symbol from raw_data that matches the evidence score,
        then construct a weekly call contract.
        """
        if not evidence or not isinstance(raw_data, dict):
            return None

        # Re-score to find which symbol produced this evidence set
        best_symbol = None
        best_score = -1.0
        for symbol, data in raw_data.items():
            sym_evidence = self._score_symbol(symbol, data)
            bullish_count = sum(1 for e in sym_evidence if e.bullish)
            if bullish_count < self.min_evidence_items:
                continue
            score = sum(e.weight for e in sym_evidence if e.bullish)
            if score > best_score:
                best_score = score
                best_symbol = symbol

        if best_symbol is None:
            return None

        data = raw_data[best_symbol]
        prices = data.get("prices", [])
        if not prices:
            return None

        stock_price = prices[-1]
        strike = round(stock_price / 5.0) * 5.0
        estimated_mark = max(0.50, round(stock_price * 0.025, 2))
        bid = round(estimated_mark * 0.95, 2)
        ask = round(estimated_mark * 1.05, 2)
        if ask < 0.10:
            ask = 0.10
            bid = 0.09

        expiry = _nearest_weekly_friday()

        return OptionContract(
            symbol=best_symbol,
            direction="CALL",
            strike=strike,
            expiry=expiry,
            bid_per_share=bid,
            ask_per_share=ask,
            mark_per_share=estimated_mark,
            open_interest=0,
            volume=0,
        )

    # ─── Market data helpers ──────────────────────────────────────────────

    async def _fetch_price_volume(
        self, symbol: str, period: str = "1mo"
    ) -> tuple[list[float], list[float]]:
        """
        Fetch historical closing prices and volumes using yfinance.
        Returns (prices, volumes) as lists; empty lists on error.
        Runs blocking yfinance call in a thread pool to avoid blocking the event loop.
        """
        loop = asyncio.get_running_loop()
        try:
            prices, volumes = await loop.run_in_executor(
                None, _yfinance_fetch, symbol, period
            )
            return prices, volumes
        except Exception as exc:
            logger.warning("yfinance fetch failed for %s: %s", symbol, exc)
            return [], []

    async def _fetch_sector_relative_return(self, period: str = "5d") -> float | None:
        """
        Fetch the relative return of XLK vs SPY over `period`.
        Returns float (positive = tech outperforming) or None on error.
        """
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, _yfinance_relative_return, _TECH_ETF, _MARKET_ETF, period
            )
        except Exception as exc:
            logger.warning("Sector relative return fetch failed: %s", exc)
            return None


# ─── Blocking helpers (run in thread pool) ───────────────────────────────────

def _yfinance_fetch(symbol: str, period: str) -> tuple[list[float], list[float]]:
    """Download OHLCV for symbol. Returns (closes, volumes)."""
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period)
    if hist.empty:
        return [], []
    closes = hist["Close"].tolist()
    volumes = hist["Volume"].tolist()
    return closes, volumes


def _yfinance_relative_return(etf: str, benchmark: str, period: str) -> float | None:
    """Return ETF return minus benchmark return over period."""
    import yfinance as yf
    data = yf.download([etf, benchmark], period=period, progress=False, auto_adjust=True)
    if data.empty:
        return None
    try:
        close = data["Close"]
        if etf not in close.columns or benchmark not in close.columns:
            return None
        etf_ret = (close[etf].iloc[-1] - close[etf].iloc[0]) / close[etf].iloc[0]
        bench_ret = (close[benchmark].iloc[-1] - close[benchmark].iloc[0]) / close[benchmark].iloc[0]
        return float(etf_ret - bench_ret)
    except Exception:
        return None

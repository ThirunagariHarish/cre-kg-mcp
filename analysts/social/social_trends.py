"""
analysts/social/social_trends.py — Social Trends Analyst (M4.1).

Monitors Reddit (r/wallstreetbets, r/stocks, r/options), StockTwits trending,
and Google Trends for 2σ spikes in ticker mentions/interest.

Wake: every 10 minutes during RTH.

Evidence items (must have >= 2 bullish to emit a signal):
  1. Reddit_spike:        2σ above 30d baseline            (weight=0.30)
  2. StockTwits_bullish:  >60% bullish sentiment            (weight=0.25)
  3. Google_trends_spike: >80 interest vs <50 baseline     (weight=0.25)
  4. Option_volume:       > 500k daily contracts            (weight=0.20)

Exit: TA_RULES — Technical Analyst calls the exit.
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from core.base_analyst import BaseAnalyst, WakeEvent
from core.file_writer import atomic_write_json, read_json
from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    TradeSignal,
)

logger = logging.getLogger("analyst.social_trends")

# ─── Constants ────────────────────────────────────────────────────────────────

_BASELINE_PATH = Path("shared/state/social_baseline.json")

_REDDIT_SUBREDDITS = ["wallstreetbets", "stocks", "options"]
_REDDIT_POST_LIMIT = 1000

# Spike detection: current mentions > mean + 2 * std
_SIGMA_THRESHOLD = 2.0

# Minimum option volume to emit a signal
_MIN_OPTION_VOLUME = 500_000

# StockTwits bullish sentiment threshold
_STOCKTWITS_BULLISH_PCT = 0.60

# Google Trends thresholds (0-100 scale)
_GTRENDS_SPIKE_MIN = 80
_GTRENDS_BASELINE_MAX = 50

# Rolling baseline window in days
_BASELINE_DAYS = 30

# RTH bounds (ET, fixed UTC-4 offset)
_RTH_OPEN_HOUR_ET = 9
_RTH_OPEN_MINUTE_ET = 30
_RTH_CLOSE_HOUR_ET = 16

# StockTwits API
_STOCKTWITS_TRENDING_URL = "https://api.stocktwits.com/api/2/streams/trending.json"


# ─── RTH guard ────────────────────────────────────────────────────────────────

def _is_rth(dt: datetime | None = None) -> bool:
    """True if dt (or now) falls within RTH (9:30–16:00 ET, Mon–Fri)."""
    dt = dt or datetime.now(tz=timezone.utc)
    et_offset = timedelta(hours=-4)
    et_time = dt + et_offset
    if et_time.weekday() >= 5:
        return False
    rth_start = et_time.replace(hour=_RTH_OPEN_HOUR_ET, minute=_RTH_OPEN_MINUTE_ET, second=0, microsecond=0)
    rth_end = et_time.replace(hour=_RTH_CLOSE_HOUR_ET, minute=0, second=0, microsecond=0)
    return rth_start <= et_time < rth_end


# ─── Baseline helpers ─────────────────────────────────────────────────────────

def _load_baseline(path: Path = _BASELINE_PATH) -> dict[str, dict[str, int]]:
    """
    Load the 30-day mention baseline.
    Format: {ticker: {date_str: mention_count, ...}}
    Returns {} on missing / malformed file — safe to start fresh.
    """
    data = read_json(path, default={})
    if not isinstance(data, dict):
        logger.warning("Baseline file has unexpected format — starting fresh")
        return {}
    return data


def _save_baseline(baseline: dict[str, dict[str, int]], path: Path = _BASELINE_PATH) -> None:
    """Atomically write the updated baseline."""
    atomic_write_json(path, baseline)


def _update_baseline(
    baseline: dict[str, dict[str, int]],
    ticker: str,
    mention_count: int,
    today: date | None = None,
) -> dict[str, dict[str, int]]:
    """
    Add today's mention count for ticker, prune entries older than 30 days.
    Returns the (mutated) baseline dict.
    """
    today = today or datetime.now(tz=timezone.utc).date()
    cutoff = today - timedelta(days=_BASELINE_DAYS)

    if ticker not in baseline:
        baseline[ticker] = {}

    baseline[ticker][str(today)] = mention_count

    # Prune old entries
    baseline[ticker] = {
        d: v for d, v in baseline[ticker].items()
        if date.fromisoformat(d) >= cutoff
    }
    return baseline


def _is_spike(
    baseline: dict[str, dict[str, int]],
    ticker: str,
    current_count: int,
    today: date | None = None,
) -> bool:
    """
    Returns True if current_count > mean + 2σ of the 30-day baseline
    (excluding today's entry so we compare against historical data only).
    Returns False when there are fewer than 3 historical data points.
    """
    today_str = str(today or datetime.now(tz=timezone.utc).date())
    history = {
        d: v for d, v in baseline.get(ticker, {}).items()
        if d != today_str
    }

    values = list(history.values())
    if len(values) < 3:
        logger.debug("Insufficient baseline for %s (%d points) — no spike detection", ticker, len(values))
        return False

    mean = statistics.mean(values)
    std = statistics.stdev(values)

    if std == 0:
        return current_count > mean

    threshold = mean + _SIGMA_THRESHOLD * std
    logger.debug(
        "Spike check %s: current=%d threshold=%.1f (mean=%.1f std=%.1f)",
        ticker, current_count, threshold, mean, std,
    )
    return current_count > threshold


# ─── Data source fetchers (blocking helpers for thread pool) ──────────────────

def _reddit_mention_counts(subreddits: list[str], post_limit: int) -> dict[str, int]:
    """
    Count ticker mentions across recent posts in the given subreddits.
    Requires REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT in env.
    Returns {} (not raises) when credentials are missing.
    """
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT")

    if not client_id or not client_secret or not user_agent:
        logger.warning(
            "Reddit credentials not set (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / "
            "REDDIT_USER_AGENT) — skipping Reddit data source"
        )
        return {}

    try:
        import praw  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("praw is not installed — skipping Reddit data source")
        return {}

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        counts: dict[str, int] = {}
        for sub_name in subreddits:
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.new(limit=post_limit):
                    text = f"{post.title} {post.selftext}".upper()
                    _count_tickers_in_text(text, counts)
            except Exception as exc:
                logger.warning("Error fetching r/%s: %s", sub_name, exc)
        return counts
    except Exception as exc:
        logger.warning("Reddit client init failed: %s — skipping", exc)
        return {}


def _count_tickers_in_text(text: str, counts: dict[str, int]) -> None:
    """
    Scan text for common uppercase ticker patterns (2-5 capital letters preceded
    by $ or surrounded by word boundaries) and increment counts.
    This is intentionally simple — false positives are tolerable for a
    social-trends signal (it's one of four evidence items).
    """
    import re
    # Match $TICKER or standalone ALL-CAPS words 2-5 chars that look like tickers
    ticker_pattern = re.compile(r'\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\b')
    for m in ticker_pattern.finditer(text):
        ticker = m.group(1) or m.group(2)
        if ticker:
            counts[ticker] = counts.get(ticker, 0) + 1


def _stocktwits_trending() -> dict[str, dict]:
    """
    Fetch trending tickers from StockTwits (no API key required).
    Returns {ticker: {"mentions": int, "bullish_pct": float | None}}.
    Returns {} on network error.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(_STOCKTWITS_TRENDING_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("StockTwits fetch failed: %s — skipping", exc)
        return {}

    result: dict[str, dict] = {}
    for item in data.get("messages", []):
        try:
            symbol = item.get("symbols", [{}])[0].get("symbol", "")
            if not symbol:
                continue
            sentiment_raw = item.get("entities", {}).get("sentiment", {})
            sentiment_str = sentiment_raw.get("basic", "") if isinstance(sentiment_raw, dict) else ""
        except (IndexError, AttributeError, TypeError):
            continue

        if symbol not in result:
            result[symbol] = {"bullish": 0, "bearish": 0, "neutral": 0}

        if sentiment_str == "Bullish":
            result[symbol]["bullish"] += 1
        elif sentiment_str == "Bearish":
            result[symbol]["bearish"] += 1
        else:
            result[symbol]["neutral"] += 1

    # Compute bullish_pct
    summary: dict[str, dict] = {}
    for sym, counts in result.items():
        total = counts["bullish"] + counts["bearish"]
        bullish_pct = (counts["bullish"] / total) if total > 0 else None
        summary[sym] = {
            "mentions": counts["bullish"] + counts["bearish"] + counts["neutral"],
            "bullish_pct": bullish_pct,
        }
    return summary


def _google_trends_interest(ticker: str) -> tuple[float | None, float | None]:
    """
    Fetch Google Trends interest for ticker.
    Returns (current_7d_interest, baseline_90d_avg) on 0-100 scale.
    Both values are None on failure.
    Skips gracefully if pytrends is unavailable or raises.
    """
    try:
        from pytrends.request import TrendReq  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("pytrends is not installed — skipping Google Trends data source")
        return None, None

    try:
        pt = TrendReq(hl="en-US", tz=360)
        pt.build_payload([ticker], timeframe="today 3-m")
        df = pt.interest_over_time()

        if df is None or df.empty or ticker not in df.columns:
            return None, None

        values = df[ticker].tolist()
        if len(values) < 7:
            return None, None

        current_7d = float(sum(values[-7:]) / 7)
        baseline_90d = float(sum(values[:-7]) / max(len(values) - 7, 1))
        return current_7d, baseline_90d
    except Exception as exc:
        logger.warning("Google Trends fetch failed for %s: %s — skipping", ticker, exc)
        return None, None


def _option_daily_volume(ticker: str) -> int | None:
    """
    Fetch total daily option volume for ticker via yfinance.
    Returns None on failure.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        opts = t.options
        if not opts:
            return None
        # Sum volume across all nearest expiry chains
        nearest = opts[0]
        chain = t.option_chain(nearest)
        call_vol = int(chain.calls["volume"].sum()) if not chain.calls.empty else 0
        put_vol = int(chain.puts["volume"].sum()) if not chain.puts.empty else 0
        return call_vol + put_vol
    except Exception as exc:
        logger.warning("yfinance option volume failed for %s: %s", ticker, exc)
        return None


def _current_stock_price(ticker: str) -> float | None:
    """Fetch current stock price via yfinance. Returns None on failure."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if price is None:
            hist = t.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        return float(price) if price else None
    except Exception as exc:
        logger.warning("yfinance price fetch failed for %s: %s", ticker, exc)
        return None


def _nearest_weekly_friday(from_date: date | None = None) -> date:
    today = from_date or datetime.now(tz=timezone.utc).date()
    days_ahead = (4 - today.weekday()) % 7
    if days_ahead == 0:
        return today
    return today + timedelta(days=days_ahead)


# ─── Main analyst class ───────────────────────────────────────────────────────

class SocialTrendsAnalyst(BaseAnalyst):
    """
    Social Trends Analyst — monitors Reddit, StockTwits, and Google Trends
    for 2σ spikes in ticker mentions/interest.

    Wakes every 10 minutes during RTH. Emits a TradeSignal when a ticker
    shows a 2σ spike AND has option volume > 500k.
    """

    analyst_id = "social_trends"
    source_layer = "SOCIAL"
    wake_trigger = "SCHEDULE"
    wake_interval_seconds = 600  # 10 min

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        *,
        confidence_threshold: float = 0.60,
        min_evidence_items: int = 2,
        baseline_path: Path = _BASELINE_PATH,
    ) -> None:
        exit_rules = ExitRules(strategy="TA_RULES")
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
        self._baseline_path = baseline_path
        # Loaded once on first gather_data, then kept in memory and persisted after each scan
        self._baseline: dict[str, dict[str, int]] = {}
        self._baseline_loaded = False

    # ─── BaseAnalyst abstract methods ─────────────────────────────────────────

    async def gather_data(self, trigger: WakeEvent) -> Any:
        """
        Collect social data from Reddit, StockTwits, and Google Trends.
        Returns None outside RTH (skips the cycle).
        Returns a dict with keys: reddit, stocktwits, baseline.
        """
        if not _is_rth():
            self._log.debug("Outside RTH — skipping cycle")
            return None

        # Lazy-load baseline on first real cycle
        if not self._baseline_loaded:
            self._baseline = _load_baseline(self._baseline_path)
            self._baseline_loaded = True

        loop = asyncio.get_running_loop()

        reddit_task = loop.run_in_executor(
            None,
            _reddit_mention_counts,
            _REDDIT_SUBREDDITS,
            _REDDIT_POST_LIMIT,
        )
        stocktwits_task = loop.run_in_executor(None, _stocktwits_trending)

        reddit_counts, stocktwits_data = await asyncio.gather(
            reddit_task, stocktwits_task, return_exceptions=True
        )

        if isinstance(reddit_counts, Exception):
            self._log.warning("Reddit gather raised: %s", reddit_counts)
            reddit_counts = {}

        if isinstance(stocktwits_data, Exception):
            self._log.warning("StockTwits gather raised: %s", stocktwits_data)
            stocktwits_data = {}

        return {
            "reddit": reddit_counts,
            "stocktwits": stocktwits_data,
            "baseline": self._baseline,
        }

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        """
        Find the most spiking ticker across all social sources and build evidence.
        Returns [] if no ticker has a 2σ spike or option volume > 500k.
        """
        if not isinstance(raw_data, dict):
            return []

        reddit: dict[str, int] = raw_data.get("reddit", {})
        stocktwits: dict[str, dict] = raw_data.get("stocktwits", {})
        baseline: dict[str, dict[str, int]] = raw_data.get("baseline", {})

        # Gather all candidate tickers across both sources
        candidates: set[str] = set(reddit.keys()) | set(stocktwits.keys())

        best: tuple[float, list[Evidence], str] | None = None

        for ticker in candidates:
            reddit_count = reddit.get(ticker, 0)
            spike = _is_spike(baseline, ticker, reddit_count)

            # Skip if no Reddit spike — Reddit is the primary signal driver
            if not spike and reddit_count == 0:
                continue

            # Gather remaining evidence in thread pool
            loop = asyncio.get_running_loop()
            opt_vol_task = loop.run_in_executor(None, _option_daily_volume, ticker)
            gtrends_task = loop.run_in_executor(None, _google_trends_interest, ticker)

            opt_vol_result, gtrends_result = await asyncio.gather(
                opt_vol_task, gtrends_task, return_exceptions=True
            )

            opt_vol: int | None = None if isinstance(opt_vol_result, Exception) else opt_vol_result
            gtrends_current: float | None = None
            gtrends_baseline: float | None = None
            if not isinstance(gtrends_result, Exception) and isinstance(gtrends_result, tuple):
                gtrends_current, gtrends_baseline = gtrends_result

            # Gate: option volume must exceed 500k to emit
            if opt_vol is not None and opt_vol < _MIN_OPTION_VOLUME:
                self._log.debug(
                    "Ticker %s: option volume %d < %d threshold — skipping",
                    ticker, opt_vol, _MIN_OPTION_VOLUME,
                )
                # Update baseline anyway
                self._baseline = _update_baseline(self._baseline, ticker, reddit_count)
                continue

            evidence = self._build_evidence_for_ticker(
                ticker=ticker,
                reddit_count=reddit_count,
                spike=spike,
                baseline=baseline,
                stocktwits_data=stocktwits.get(ticker),
                gtrends_current=gtrends_current,
                gtrends_baseline_avg=gtrends_baseline,
                opt_vol=opt_vol,
            )

            bullish_count = sum(1 for e in evidence if e.bullish)
            if bullish_count < self.min_evidence_items:
                self._log.debug(
                    "Ticker %s: only %d/%d bullish evidence items — skipping",
                    ticker, bullish_count, self.min_evidence_items,
                )
                self._baseline = _update_baseline(self._baseline, ticker, reddit_count)
                continue

            score = sum(e.weight for e in evidence if e.bullish)
            if best is None or score > best[0]:
                best = (score, evidence, ticker)

            self._baseline = _update_baseline(self._baseline, ticker, reddit_count)

        # Persist updated baseline
        if self._baseline:
            try:
                _save_baseline(self._baseline, self._baseline_path)
            except Exception as exc:
                self._log.error("Failed to save baseline: %s", exc)

        if best is None:
            return []

        # Store the winning ticker in raw_data so select_contract can use it
        raw_data["_best_ticker"] = best[2]
        return best[1]

    async def select_contract(
        self,
        evidence: list[Evidence],
        raw_data: Any,
    ) -> OptionContract | None:
        """
        Select a weekly CALL (or PUT) contract for the winning ticker.
        Uses yfinance for current price to derive a reasonable strike.
        """
        if not evidence or not isinstance(raw_data, dict):
            return None

        ticker = raw_data.get("_best_ticker")
        if not ticker:
            return None

        direction = self._infer_direction(evidence)

        loop = asyncio.get_running_loop()
        try:
            price = await loop.run_in_executor(None, _current_stock_price, ticker)
        except Exception as exc:
            self._log.warning("Price fetch failed for %s: %s", ticker, exc)
            price = None

        if not price:
            self._log.info("No price available for %s — cannot select contract", ticker)
            return None

        # Round strike to nearest $5 (ATM/slight-OTM)
        strike = round(price / 5.0) * 5.0

        # Estimate mark at ~2.5% of stock price
        estimated_mark = max(0.50, round(price * 0.025, 2))
        bid = round(estimated_mark * 0.95, 2)
        ask = round(estimated_mark * 1.05, 2)
        if ask < 0.10:
            ask = 0.10
            bid = 0.09

        expiry = _nearest_weekly_friday()

        return OptionContract(
            symbol=ticker,
            direction=direction,
            strike=strike,
            expiry=expiry,
            bid_per_share=bid,
            ask_per_share=ask,
            mark_per_share=estimated_mark,
            open_interest=0,
            volume=0,
        )

    # ─── Evidence builder ──────────────────────────────────────────────────────

    def _build_evidence_for_ticker(
        self,
        ticker: str,
        reddit_count: int,
        spike: bool,
        baseline: dict[str, dict[str, int]],
        stocktwits_data: dict | None,
        gtrends_current: float | None,
        gtrends_baseline_avg: float | None,
        opt_vol: int | None,
    ) -> list[Evidence]:
        """Assemble the four Evidence items for a single ticker."""
        evidence: list[Evidence] = []

        # 1. Reddit spike (weight=0.30)
        history_values = list(baseline.get(ticker, {}).values())
        mean = statistics.mean(history_values) if len(history_values) >= 3 else 0.0
        std = statistics.stdev(history_values) if len(history_values) >= 3 else 0.0
        sigma_label = (
            f"{(reddit_count - mean) / std:.1f}σ above baseline"
            if std > 0 else "insufficient baseline"
        )
        evidence.append(Evidence(
            indicator="reddit_spike",
            value=reddit_count,
            interpretation=(
                f"Reddit mentions: {reddit_count} "
                f"({'2σ spike' if spike else 'normal'}) — {sigma_label}"
            ),
            weight=0.30,
            bullish=spike,
        ))

        # 2. StockTwits bullish sentiment (weight=0.25)
        bullish_pct = stocktwits_data.get("bullish_pct") if stocktwits_data else None
        is_bullish_sentiment = bullish_pct is not None and bullish_pct > _STOCKTWITS_BULLISH_PCT
        evidence.append(Evidence(
            indicator="stocktwits_bullish",
            value=round(bullish_pct * 100, 1) if bullish_pct is not None else None,
            interpretation=(
                f"StockTwits bullish sentiment: {bullish_pct * 100:.1f}% "
                f"({'above' if is_bullish_sentiment else 'below'} {_STOCKTWITS_BULLISH_PCT * 100:.0f}% threshold)"
                if bullish_pct is not None else "StockTwits sentiment unavailable"
            ),
            weight=0.25,
            bullish=is_bullish_sentiment,
        ))

        # 3. Google Trends spike (weight=0.25)
        is_gtrends_spike = (
            gtrends_current is not None
            and gtrends_baseline_avg is not None
            and gtrends_current > _GTRENDS_SPIKE_MIN
            and gtrends_baseline_avg < _GTRENDS_BASELINE_MAX
        )
        evidence.append(Evidence(
            indicator="google_trends_spike",
            value=round(gtrends_current, 1) if gtrends_current is not None else None,
            interpretation=(
                f"Google Trends interest: {gtrends_current:.0f}/100 "
                f"(baseline avg {gtrends_baseline_avg:.0f}) — "
                f"{'spike detected' if is_gtrends_spike else 'no spike'}"
                if gtrends_current is not None else "Google Trends data unavailable"
            ),
            weight=0.25,
            bullish=is_gtrends_spike,
        ))

        # 4. Option volume (weight=0.20)
        is_high_vol = opt_vol is not None and opt_vol > _MIN_OPTION_VOLUME
        evidence.append(Evidence(
            indicator="option_volume",
            value=opt_vol,
            interpretation=(
                f"Daily option volume: {opt_vol:,} "
                f"({'above' if is_high_vol else 'below'} {_MIN_OPTION_VOLUME:,} threshold)"
                if opt_vol is not None else "Option volume data unavailable"
            ),
            weight=0.20,
            bullish=is_high_vol,
        ))

        return evidence

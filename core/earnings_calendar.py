"""Earnings Calendar — Alpha Vantage backed with local JSON cache."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent / "shared" / "state" / "earnings_calendar.json"
EARNINGS_GATE_DAYS = 14

_AV_BASE = "https://www.alphavantage.co/query"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_cache() -> dict[str, str]:
    """Return {SYMBOL: 'YYYY-MM-DD'} dict from cache, or empty dict."""
    try:
        if _CACHE_PATH.exists():
            with _CACHE_PATH.open() as f:
                return json.load(f)
    except Exception as exc:
        logger.warning("earnings_calendar: failed to read cache %s: %s", _CACHE_PATH, exc)
    return {}


def _save_cache(data: dict[str, str]) -> None:
    """Atomically write cache using a temp file + rename."""
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_CACHE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, _CACHE_PATH)
    except Exception as exc:
        logger.error("earnings_calendar: failed to save cache: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_earnings_date(symbol: str) -> Optional[date]:
    """Return next earnings date for *symbol* from local cache, or None."""
    cache = _load_cache()
    raw = cache.get(symbol.upper())
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        logger.warning("earnings_calendar: invalid date %r for %s", raw, symbol)
        return None


async def refresh_calendar(symbols: list[str]) -> None:
    """Fetch upcoming earnings dates from Alpha Vantage and update local cache.

    Uses the free-tier EARNINGS endpoint. Sleeps 0.5 s between requests.
    Failures per symbol are logged but never raised.
    """
    api_key = os.getenv("ALPHA_VANTAGE_KEY", "demo")
    cache = _load_cache()

    async with aiohttp.ClientSession() as session:
        for symbol in symbols:
            sym = symbol.upper()
            try:
                url = (
                    f"{_AV_BASE}?function=EARNINGS"
                    f"&symbol={sym}&apikey={api_key}"
                )
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)

                quarterly = data.get("quarterlyEarnings", [])
                today = date.today()
                future_dates: list[date] = []

                for entry in quarterly:
                    raw_date = entry.get("reportedDate") or entry.get("fiscalDateEnding")
                    if not raw_date:
                        continue
                    try:
                        d = date.fromisoformat(raw_date)
                        if d >= today:
                            future_dates.append(d)
                    except ValueError:
                        continue

                if future_dates:
                    next_date = min(future_dates)
                    cache[sym] = next_date.isoformat()
                    logger.info("earnings_calendar: %s -> %s", sym, next_date)
                else:
                    logger.info("earnings_calendar: no future earnings found for %s", sym)

            except Exception as exc:
                logger.warning("earnings_calendar: failed to fetch %s: %s", sym, exc)

            await asyncio.sleep(0.5)

    _save_cache(cache)


def is_within_earnings_window(symbol: str, gate_days: int = EARNINGS_GATE_DAYS) -> bool:
    """Return True if earnings fall within *gate_days* of today (in either direction)."""
    d = get_earnings_date(symbol)
    if d is None:
        return False
    return abs((d - date.today()).days) <= gate_days


def days_to_earnings(symbol: str) -> Optional[int]:
    """Return number of calendar days until earnings, or None if unknown.

    Negative value means earnings already passed (and are still in cache).
    """
    d = get_earnings_date(symbol)
    if d is None:
        return None
    return (d - date.today()).days

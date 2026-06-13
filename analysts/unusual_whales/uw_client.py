"""
analysts/unusual_whales/uw_client.py — Unusual Whales REST API client.

Features:
  - Token bucket rate limiting (60 req/min default)
  - File-based cache (TTL 60s) in shared/cache/uw/
  - 404 → serve cache + log warning (never crash)
  - Any other error → return [] / {} (never crash)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("shared/cache/uw")
_CACHE_TTL_SECONDS = 60


def _cache_path(endpoint_slug: str, params: dict[str, Any]) -> Path:
    """Deterministic cache file path for an endpoint + params combination."""
    params_str = json.dumps(params, sort_keys=True)
    params_hash = hashlib.sha256(params_str.encode()).hexdigest()[:16]
    filename = f"uw_{endpoint_slug}_{params_hash}.json"
    return _CACHE_DIR / filename


def _read_cache(path: Path) -> Any | None:
    """
    Read cached response if it exists and is within TTL.
    Returns None if missing, expired, or malformed.
    """
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None

    if time.time() - mtime > _CACHE_TTL_SECONDS:
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(path: Path, data: Any) -> None:
    """Write data to cache atomically."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as exc:
        logger.warning("Failed to write UW cache %s: %s", path, exc)


class UWClient:
    """
    Async client for the Unusual Whales REST API.

    Rate limiting: token bucket at `requests_per_minute` tokens.
    Caching: file-based in shared/cache/uw/ with 60-second TTL.
    Error policy: 404 → serve cache; all other errors → return empty (never raise).
    """

    BASE_URL = "https://api.unusualwhales.com/api"

    def __init__(
        self,
        api_token: str,
        *,
        requests_per_minute: int = 60,
    ) -> None:
        self._api_token = api_token
        self._requests_per_minute = requests_per_minute

        # Token bucket state
        self._tokens: float = float(requests_per_minute)
        self._last_refill: float = time.monotonic()
        self._rate_lock = asyncio.Lock()

        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
        }

    # ─── Rate limiting ────────────────────────────────────────────────────

    async def _acquire_token(self) -> None:
        """
        Token bucket: replenish tokens based on elapsed time, then consume one.
        Sleeps if the bucket is empty.
        """
        async with self._rate_lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                refill = elapsed * (self._requests_per_minute / 60.0)
                self._tokens = min(float(self._requests_per_minute), self._tokens + refill)
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # Sleep until we have a token — calculate exact wait time
                deficit = 1.0 - self._tokens
                sleep_seconds = deficit / (self._requests_per_minute / 60.0)
                await asyncio.sleep(sleep_seconds)

    # ─── Internal HTTP helper ─────────────────────────────────────────────

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        cache_slug: str | None = None,
    ) -> Any:
        """
        Issue a GET request with rate limiting and caching.

        On 404: attempt to serve cached response, log warning.
        On any exception: log error and return None.
        """
        params = params or {}
        slug = cache_slug or path.strip("/").replace("/", "_")
        cache_file = _cache_path(slug, params)

        await self._acquire_token()

        url = f"{self.BASE_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params, headers=self._headers)

            if resp.status_code == 404:
                cached = _read_cache(cache_file)
                if cached is not None:
                    logger.warning("UW 404 for %s — serving cache", path)
                    return cached
                logger.warning("UW 404 for %s — no cache available, returning empty", path)
                return None

            resp.raise_for_status()
            data = resp.json()
            _write_cache(cache_file, data)
            return data

        except httpx.HTTPStatusError as exc:
            logger.error("UW HTTP error %s for %s: %s", exc.response.status_code, path, exc)
            return None
        except Exception as exc:
            logger.error("UW request failed for %s: %s", path, exc)
            # Try cache as fallback
            cached = _read_cache(cache_file)
            if cached is not None:
                logger.info("UW serving stale cache for %s after error", path)
                return cached
            return None

    # ─── Public API methods ───────────────────────────────────────────────

    async def get_option_flow(self, symbol: str) -> list[dict]:
        """
        GET /option-trades/flow?ticker={symbol}

        Returns list of recent option flow records for the given symbol.
        Rate-limited and cached. On 404: serve cache. On error: return [].
        """
        symbol = symbol.upper()
        params = {"ticker": symbol}
        slug = f"option_flow_{symbol}"

        result = await self._get("/option-trades/flow", params=params, cache_slug=slug)
        if result is None:
            return []
        # API returns {"data": [...]} or directly [...]
        if isinstance(result, dict):
            return result.get("data", [])
        if isinstance(result, list):
            return result
        return []

    async def get_unusual_activity(self, min_premium: float = 50_000) -> list[dict]:
        """
        GET /options/activity?min_premium={min_premium}

        Returns unusual options activity sorted by premium descending.
        On error: return [].
        """
        params = {"min_premium": min_premium}
        result = await self._get("/options/activity", params=params, cache_slug="unusual_activity")
        if result is None:
            return []
        if isinstance(result, dict):
            data = result.get("data", [])
        elif isinstance(result, list):
            data = result
        else:
            return []

        # Sort by premium descending
        try:
            data = sorted(data, key=lambda x: float(x.get("premium", 0)), reverse=True)
        except (TypeError, ValueError):
            pass
        return data

    async def get_market_overview(self) -> dict:
        """
        GET /market/overview

        Returns market-wide call/put ratio, GEX, and other overview metrics.
        On error: return {}.
        """
        result = await self._get("/market/overview", cache_slug="market_overview")
        if result is None:
            return {}
        if isinstance(result, dict):
            return result.get("data", result)
        return {}

    async def get_stock_screener(self) -> list[dict]:
        """
        GET /options/screener

        Returns options with unusual volume from the UW screener.
        On error: return [].
        """
        result = await self._get("/options/screener", cache_slug="stock_screener")
        if result is None:
            return []
        if isinstance(result, dict):
            return result.get("data", [])
        if isinstance(result, list):
            return result
        return []

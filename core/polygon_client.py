"""
core/polygon_client.py — Polygon.io REST client for real-time options data.

Falls back to yfinance if no API key is configured.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime
from typing import Any

import httpx

from core.schemas import OptionContract

log = logging.getLogger("polygon_client")

# Module-level singleton
_client: "PolygonClient | None" = None


class PolygonClient:
    """Polygon.io REST client with in-memory TTL cache and yfinance fallback."""

    POLYGON_BASE = "https://api.polygon.io"
    CACHE_TTL = 30  # seconds

    def __init__(self, api_key: str | None = None) -> None:
        self._key = api_key or os.getenv("POLYGON_API_KEY", "")
        self._enabled = bool(self._key)
        self._http = httpx.AsyncClient(timeout=10.0)
        self._cache: dict[str, tuple[Any, float]] = {}  # key -> (data, timestamp)

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    async def get_option_quote(
        self,
        symbol: str,
        direction: str,
        strike: float,
        expiry: date,
    ) -> OptionContract | None:
        """Fetch a live option quote.  Falls back to yfinance if Polygon is not enabled."""
        if not self._enabled:
            return await self._yfinance_fallback(symbol, direction, strike, expiry)

        ticker = self._build_ticker(symbol, direction, strike, expiry)

        # Cache check
        cached = self._cache.get(ticker)
        if cached is not None:
            data, ts = cached
            if time.monotonic() - ts < self.CACHE_TTL:
                return data

        url = f"{self.POLYGON_BASE}/v3/snapshot/options/{ticker}"
        try:
            resp = await self._http.get(
                url,
                headers={"Authorization": f"Bearer {self._key}"},
            )
            if resp.status_code != 200:
                log.warning(
                    "Polygon returned %s for %s — falling back to yfinance",
                    resp.status_code,
                    ticker,
                )
                return await self._yfinance_fallback(symbol, direction, strike, expiry)

            body = resp.json()
            contract = self._parse_polygon_response(body, symbol, direction, strike, expiry)
            if contract is None:
                return await self._yfinance_fallback(symbol, direction, strike, expiry)

            self._cache[ticker] = (contract, time.monotonic())
            return contract

        except Exception as exc:
            log.warning("Polygon request failed (%s) — falling back to yfinance", exc)
            return await self._yfinance_fallback(symbol, direction, strike, expiry)

    async def get_bid_ask_spread_pct(
        self,
        symbol: str,
        direction: str,
        strike: float,
        expiry: date,
    ) -> float | None:
        """Return (ask - bid) / mid, or None if no quote available."""
        quote = await self.get_option_quote(symbol, direction, strike, expiry)
        if quote is None:
            return None
        mid = (quote.ask_per_share + quote.bid_per_share) / 2
        if mid == 0:
            return None
        return (quote.ask_per_share - quote.bid_per_share) / mid

    async def close(self) -> None:
        await self._http.aclose()

    # ─────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────

    def _build_ticker(
        self,
        symbol: str,
        direction: str,
        strike: float,
        expiry: date,
    ) -> str:
        """Build a Polygon OCC ticker string.

        Example: SPY 450 CALL 2025-12-19 -> "O:SPY251219C00450000"
        Strike is encoded in 1/1000ths of a dollar, zero-padded to 8 digits.
        """
        exp = expiry.strftime("%y%m%d")
        cp = "C" if direction.upper() == "CALL" else "P"
        strike_int = int(round(strike * 1000))
        return f"O:{symbol.upper()}{exp}{cp}{strike_int:08d}"

    def _parse_polygon_response(
        self,
        body: dict[str, Any],
        symbol: str,
        direction: str,
        strike: float,
        expiry: date,
    ) -> OptionContract | None:
        """Parse a Polygon v3 snapshot response into an OptionContract."""
        try:
            results = body.get("results", {})
            details = results.get("details", {})
            day = results.get("day", {})
            greeks = results.get("greeks", {})

            bid = float(results.get("last_quote", {}).get("bid", 0) or day.get("open", 0))
            ask = float(results.get("last_quote", {}).get("ask", 0) or day.get("close", 0))
            mark = (bid + ask) / 2

            # Ensure ask >= $0.10 (schema requirement)
            if ask < 0.10:
                ask = max(0.10, mark)
            if bid < 0.01:
                bid = max(0.01, ask - 0.01)

            return OptionContract(
                symbol=symbol.upper(),
                direction=direction.upper(),  # type: ignore[arg-type]
                strike=strike,
                expiry=expiry,
                bid_per_share=bid,
                ask_per_share=ask,
                mark_per_share=mark,
                open_interest=int(results.get("open_interest", 0) or 0),
                volume=int(day.get("volume", 0) or 0),
                implied_volatility=float(results.get("implied_volatility", 0) or 0) or None,
                delta=float(greeks.get("delta", 0) or 0) or None,
            )
        except Exception as exc:
            log.warning("Failed to parse Polygon response: %s", exc)
            return None

    async def _yfinance_fallback(
        self,
        symbol: str,
        direction: str,
        strike: float,
        expiry: date,
    ) -> OptionContract | None:
        """Fetch option data from yfinance when Polygon is unavailable."""
        try:
            import yfinance as yf  # noqa: PLC0415

            def _fetch() -> OptionContract | None:
                tick = yf.Ticker(symbol)
                chain = tick.option_chain(expiry.strftime("%Y-%m-%d"))
                df = chain.calls if direction.upper() == "CALL" else chain.puts
                if df.empty:
                    return None

                idx = (df["strike"] - strike).abs().idxmin()
                row = df.loc[idx]

                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)

                # Ensure minimum ask
                if ask < 0.10:
                    ask = 0.10
                if bid < 0.01:
                    bid = 0.01

                mark = (bid + ask) / 2
                iv = float(row.get("impliedVolatility", 0) or 0) or None

                return OptionContract(
                    symbol=symbol.upper(),
                    direction=direction.upper(),  # type: ignore[arg-type]
                    strike=strike,
                    expiry=expiry,
                    bid_per_share=bid,
                    ask_per_share=ask,
                    mark_per_share=mark,
                    open_interest=int(row.get("openInterest", 0) or 0),
                    volume=int(row.get("volume", 0) or 0),
                    implied_volatility=iv,
                )

            return await asyncio.to_thread(_fetch)

        except Exception as exc:
            log.warning("yfinance fallback failed: %s", exc)
            return None


# ─────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────

def get_polygon_client() -> PolygonClient:
    """Return the module-level singleton PolygonClient, creating it if needed."""
    global _client
    if _client is None:
        _client = PolygonClient()
    return _client

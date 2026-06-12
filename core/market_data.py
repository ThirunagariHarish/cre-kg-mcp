"""
core/market_data.py — MarketDataService: the ONLY way to access market data.

All analysts go through this service. No analyst imports yfinance, httpx,
or any data library directly. This isolates library version breakages
(yfinance MultiIndex regression, UW endpoint renames) to one file.

Legacy lesson: yfinance >=0.2.50 returns MultiIndex columns for single-ticker
calls. The flatten is done here once, so analysts never see it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


class MarketDataError(Exception):
    """Raised when market data cannot be fetched and no fallback exists."""


class OHLCV:
    """Normalized OHLCV bar — always a plain dict, never a DataFrame."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.open: float = float(data["open"])
        self.high: float = float(data["high"])
        self.low: float = float(data["low"])
        self.close: float = float(data["close"])
        self.volume: int = int(data["volume"])
        self.timestamp: datetime = data["timestamp"]

    def __repr__(self) -> str:
        return (
            f"OHLCV(ts={self.timestamp}, O={self.open}, H={self.high}, "
            f"L={self.low}, C={self.close}, V={self.volume})"
        )


class OptionQuote:
    """Normalized option quote — all prices labeled per_share AND per_contract."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.symbol: str = data["symbol"]
        self.strike: float = float(data["strike"])
        self.expiry: date = data["expiry"]
        self.direction: str = data["direction"]  # "CALL" or "PUT"

        # Always store both — no ambiguity ever
        self.bid_per_share: float = float(data["bid_per_share"])
        self.ask_per_share: float = float(data["ask_per_share"])
        self.mark_per_share: float = float(data["mark_per_share"])

        self.bid_per_contract: float = self.bid_per_share * 100
        self.ask_per_contract: float = self.ask_per_share * 100
        self.mark_per_contract: float = self.mark_per_share * 100

        self.open_interest: int = int(data.get("open_interest", 0))
        self.volume: int = int(data.get("volume", 0))
        self.implied_volatility: float | None = data.get("implied_volatility")
        self.delta: float | None = data.get("delta")

    @property
    def is_tradable(self) -> bool:
        """True if the contract has a market (ask > 0.10)."""
        return self.ask_per_share >= 0.10

    @property
    def otm_pct(self) -> float | None:
        """OTM% relative to underlying — requires underlying_price in data."""
        return None  # filled by caller who has underlying price


class MarketDataService:
    """
    Thin adapter over yfinance, UW, and other data sources.
    All I/O is async (via asyncio.to_thread for blocking libs).
    """

    def __init__(self, uw_token: str | None = None) -> None:
        self._uw_token = uw_token

    # ─── Stock data ─────────────────────────────────────────────────────

    async def get_price(self, symbol: str) -> float:
        """Current mid price for a stock or index."""
        bars = await self.get_bars(symbol, period="1d", interval="1m")
        if not bars:
            raise MarketDataError(f"No price data for {symbol}")
        return bars[-1].close

    async def get_bars(
        self,
        symbol: str,
        period: str = "5d",
        interval: str = "1d",
    ) -> list[OHLCV]:
        """OHLCV bars. Uses yfinance via asyncio.to_thread (blocking I/O)."""
        return await asyncio.to_thread(self._fetch_bars_sync, symbol, period, interval)

    def _fetch_bars_sync(self, symbol: str, period: str, interval: str) -> list[OHLCV]:
        import pandas as pd
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)

        if df.empty:
            return []

        # Legacy lesson: flatten MultiIndex — yfinance >=0.2.50 wraps columns in MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # Normalize column names to lowercase
        df.columns = [c.lower() for c in df.columns]

        result = []
        for ts, row in df.iterrows():
            try:
                result.append(OHLCV({
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row.get("volume", 0),
                    "timestamp": ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                }))
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed OHLCV row for %s: %s", symbol, exc)

        return result

    async def get_volume_ratio(self, symbol: str, lookback_days: int = 20) -> float:
        """
        Current-day volume / 20-day average volume.
        >2.0 = unusual volume.
        """
        bars = await self.get_bars(symbol, period=f"{lookback_days + 1}d", interval="1d")
        if len(bars) < 2:
            return 1.0
        avg_vol = sum(b.volume for b in bars[:-1]) / len(bars[:-1])
        if avg_vol == 0:
            return 1.0
        return bars[-1].volume / avg_vol

    # ─── Option chain ────────────────────────────────────────────────────

    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        direction: str,
        min_ask: float = 0.10,
    ) -> list[OptionQuote]:
        """
        Returns tradable option contracts for a symbol/expiry/direction.
        Filters out penny options (ask < min_ask).

        NOTE: SPX, NDX, VIX are index options — yfinance may return empty chain.
        For these, caller should use broker API directly.
        """
        return await asyncio.to_thread(
            self._fetch_option_chain_sync, symbol, expiry, direction, min_ask
        )

    def _fetch_option_chain_sync(
        self,
        symbol: str,
        expiry: date,
        direction: str,
        min_ask: float,
    ) -> list[OptionQuote]:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        expiry_str = expiry.strftime("%Y-%m-%d")

        try:
            chain = ticker.option_chain(expiry_str)
        except Exception as exc:
            logger.warning("Option chain fetch failed for %s %s: %s", symbol, expiry_str, exc)
            return []

        df = chain.calls if direction == "CALL" else chain.puts

        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            try:
                ask = float(row.get("ask", 0))
                if ask < min_ask:
                    continue
                bid = float(row.get("bid", 0))
                mark = (bid + ask) / 2
                results.append(OptionQuote({
                    "symbol": symbol,
                    "strike": float(row["strike"]),
                    "expiry": expiry,
                    "direction": direction,
                    "bid_per_share": bid,
                    "ask_per_share": ask,
                    "mark_per_share": mark,
                    "open_interest": int(row.get("openInterest", 0)),
                    "volume": int(row.get("volume", 0)),
                    "implied_volatility": float(row["impliedVolatility"])
                        if "impliedVolatility" in row else None,
                }))
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("Skipping malformed option row: %s", exc)

        return results

    # ─── Unusual Whales ──────────────────────────────────────────────────

    async def get_uw_flow(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Unusual Whales option flow alerts."""
        if not self._uw_token:
            logger.warning("UW token not set — returning empty flow")
            return []
        return await asyncio.to_thread(self._fetch_uw_flow_sync, symbol)

    def _fetch_uw_flow_sync(self, symbol: str | None) -> list[dict[str, Any]]:
        import httpx

        # Version-pinned endpoint — update if UW renames again
        url = "https://api.unusualwhales.com/api/option-trades/flow-alerts"
        headers = {"Authorization": f"Bearer {self._uw_token}"}
        params: dict[str, str] = {}
        if symbol:
            params["ticker"] = symbol

        try:
            resp = httpx.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json().get("data", [])  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.error(
                    "UW flow endpoint returned 404 — endpoint may have been renamed. "
                    "Check UW API changelog. URL: %s", url
                )
            else:
                logger.error("UW flow request failed: %s", exc)
            return []
        except Exception as exc:
            logger.error("UW flow unexpected error: %s", exc)
            return []

    async def get_gex(self) -> float | None:
        """Gamma Exposure (GEX) for SPX. Positive = bullish, negative = bearish."""
        if not self._uw_token:
            return None

        url = "https://api.unusualwhales.com/api/market/market-tide"
        headers = {"Authorization": f"Bearer {self._uw_token}"}

        try:
            import httpx
            resp = await asyncio.to_thread(
                lambda: httpx.get(url, headers=headers, timeout=10)
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("data", {}).get("gex", 0))
        except Exception as exc:
            logger.warning("GEX fetch failed: %s", exc)
            return None

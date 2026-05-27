"""
yfinance market data adapter.
Implements IMarketDataAdapter using Yahoo Finance data.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


class YFinanceMarketDataAdapter:
    """
    Market data adapter backed by yfinance.
    Uses asyncio.run_in_executor for thread-safe async access.
    """

    def __init__(self, cache_ttl_seconds: int = 60) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._quote_cache: dict[str, tuple[dict[str, Any], float]] = {}

    async def _run_sync(self, func: Any, *args: Any) -> Any:
        """Run a synchronous yfinance call in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, func, *args)

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Get current quote with basic caching."""
        import time

        now = time.monotonic()
        if symbol in self._quote_cache:
            cached, ts = self._quote_cache[symbol]
            if now - ts < self._cache_ttl:
                return cached

        try:
            import yfinance as yf  # type: ignore

            def _fetch() -> dict[str, Any]:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                fast = ticker.fast_info
                return {
                    "symbol": symbol.upper(),
                    "price": getattr(fast, "last_price", None) or info.get("regularMarketPrice"),
                    "open": getattr(fast, "open", None) or info.get("regularMarketOpen"),
                    "high": getattr(fast, "day_high", None) or info.get("regularMarketDayHigh"),
                    "low": getattr(fast, "day_low", None) or info.get("regularMarketDayLow"),
                    "volume": getattr(fast, "three_month_average_volume", None) or info.get("regularMarketVolume"),
                    "previous_close": getattr(fast, "previous_close", None) or info.get("regularMarketPreviousClose"),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                    "52w_high": info.get("fiftyTwoWeekHigh"),
                    "52w_low": info.get("fiftyTwoWeekLow"),
                    "currency": info.get("currency", "USD"),
                    "exchange": info.get("exchange"),
                    "fetched_at": datetime.utcnow().isoformat(),
                }

            result = await self._run_sync(_fetch)
            self._quote_cache[symbol] = (result, now)
            return result
        except Exception as exc:
            logger.error("yfinance quote error for %s: %s", symbol, exc)
            return {"symbol": symbol, "error": str(exc)}

    async def get_ohlcv(
        self,
        symbol: str,
        period: str = "1d",
        interval: str = "1m",
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV bars."""
        try:
            import yfinance as yf  # type: ignore

            def _fetch() -> list[dict[str, Any]]:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period=period, interval=interval)
                if df.empty:
                    return []
                df = df.reset_index()
                records = []
                for _, row in df.iterrows():
                    records.append({
                        "timestamp": str(row.get("Datetime") or row.get("Date")),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": float(row["Volume"]),
                    })
                return records

            return await self._run_sync(_fetch)
        except Exception as exc:
            logger.error("yfinance OHLCV error for %s: %s", symbol, exc)
            return []

    async def get_fundamentals(self, symbol: str) -> dict[str, Any]:
        """Fetch fundamental data."""
        try:
            import yfinance as yf  # type: ignore

            def _fetch() -> dict[str, Any]:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                return {
                    "symbol": symbol.upper(),
                    "company_name": info.get("longName"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "market_cap": info.get("marketCap"),
                    "enterprise_value": info.get("enterpriseValue"),
                    "trailing_pe": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "peg_ratio": info.get("pegRatio"),
                    "price_to_book": info.get("priceToBook"),
                    "profit_margins": info.get("profitMargins"),
                    "revenue_growth": info.get("revenueGrowth"),
                    "earnings_growth": info.get("earningsGrowth"),
                    "total_debt": info.get("totalDebt"),
                    "total_cash": info.get("totalCash"),
                    "free_cashflow": info.get("freeCashflow"),
                    "beta": info.get("beta"),
                    "employees": info.get("fullTimeEmployees"),
                    "description": info.get("longBusinessSummary"),
                }

            return await self._run_sync(_fetch)
        except Exception as exc:
            logger.error("yfinance fundamentals error for %s: %s", symbol, exc)
            return {"symbol": symbol, "error": str(exc)}

    async def get_multiple_quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Batch quote fetch."""
        results = await asyncio.gather(
            *[self.get_quote(s) for s in symbols],
            return_exceptions=True,
        )
        return {
            sym: (res if isinstance(res, dict) else {"symbol": sym, "error": str(res)})
            for sym, res in zip(symbols, results)
        }

    async def get_quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Alias for get_multiple_quotes with normalized output format."""
        results: dict[str, dict[str, Any]] = {}
        for sym in symbols:
            try:
                q = await self.get_quote(sym.upper())
                price = q.get("price") or 0.0
                prev_close = q.get("previous_close") or price or 0.0
                change = price - prev_close
                change_pct = (change / prev_close * 100.0) if prev_close else 0.0
                results[sym.upper()] = {
                    "symbol": sym.upper(),
                    "last": float(price or 0),
                    "previousClose": float(prev_close or 0),
                    "change": round(change, 4),
                    "changePercent": round(change_pct, 2),
                    "volume": int(q.get("volume") or 0),
                    "open": float(q.get("open") or 0),
                    "high": float(q.get("high") or 0),
                    "low": float(q.get("low") or 0),
                    "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                }
            except Exception:
                pass
        return results

    async def get_news(self, symbols: list[str], limit: int = 20) -> list[dict[str, Any]]:
        """Fetch recent news for a list of symbols via yfinance."""
        try:
            import yfinance as yf  # type: ignore

            def _fetch() -> list[dict[str, Any]]:
                seen: dict[str, dict[str, Any]] = {}
                for symbol in symbols:
                    try:
                        ticker = yf.Ticker(symbol)
                        items = ticker.news or []
                        for item in items:
                            uid = item.get("uuid") or item.get("id", "")
                            if not uid or uid in seen:
                                continue
                            seen[uid] = {
                                "id": uid,
                                "ticker": symbol,
                                "headline": item.get("title", ""),
                                "summary": item.get("title", ""),
                                "source": item.get("publisher", "Unknown"),
                                "url": item.get("link", ""),
                                "timestamp": item.get("providerPublishTime", 0),
                                "relatedTickers": item.get("relatedTickers", []),
                                "sentiment": "NEUTRAL",
                            }
                    except Exception as inner_exc:
                        logger.warning("yfinance news error for %s: %s", symbol, inner_exc)
                sorted_items = sorted(seen.values(), key=lambda x: x["timestamp"], reverse=True)
                return sorted_items[:limit]

            return await self._run_sync(_fetch)
        except Exception as exc:
            logger.error("yfinance get_news error: %s", exc)
            return []

    async def get_short_interest(self, symbol: str) -> dict[str, Any]:
        """Fetch short interest data for a symbol via yfinance."""
        try:
            import yfinance as yf  # type: ignore

            def _fetch() -> dict[str, Any]:
                info = yf.Ticker(symbol).info
                return {
                    "symbol": symbol.upper(),
                    "shortRatio": info.get("shortRatio"),
                    "shortPercentOfFloat": info.get("shortPercentOfFloat"),
                    "sharesShort": info.get("sharesShort"),
                    "sharesShortPriorMonth": info.get("sharesShortPriorMonth"),
                    "floatShares": info.get("floatShares"),
                    "impliedVolatility": info.get("impliedVolatility"),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }

            return await self._run_sync(_fetch)
        except Exception as exc:
            logger.error("yfinance short interest error for %s: %s", symbol, exc)
            return {"symbol": symbol.upper(), "error": str(exc)}

    async def search_symbols(self, query: str) -> list[dict[str, Any]]:
        """Search for symbols using yfinance."""
        try:
            import yfinance as yf  # type: ignore

            def _fetch() -> list[dict[str, Any]]:
                ticker = yf.Ticker(query.upper())
                info = ticker.info
                if info.get("symbol"):
                    return [{
                        "symbol": info["symbol"],
                        "name": info.get("longName", ""),
                        "exchange": info.get("exchange", ""),
                        "type": "equity",
                    }]
                return []

            return await self._run_sync(_fetch)
        except Exception as exc:
            logger.warning("Symbol search failed for %s: %s", query, exc)
            return []

    async def get_options_expiries(self, symbol: str) -> list[str]:
        try:
            import yfinance as yf  # type: ignore

            def _fetch() -> list[str]:
                ticker = yf.Ticker(symbol.upper())
                return list(ticker.options)  # returns tuple of date strings like "2025-06-20"

            return await self._run_sync(_fetch)
        except Exception as exc:
            logger.error("yfinance options expiries error for %s: %s", symbol, exc)
            return []

    async def get_options_chain(self, symbol: str, expiry: str) -> dict[str, Any]:
        try:
            import yfinance as yf  # type: ignore

            def _fetch() -> dict[str, Any]:
                ticker = yf.Ticker(symbol.upper())
                chain = ticker.option_chain(expiry)

                def df_to_list(df: Any) -> list[dict[str, Any]]:
                    records = []
                    for _, row in df.iterrows():
                        records.append({
                            "strike": float(row.get("strike", 0)),
                            "lastPrice": float(row.get("lastPrice", 0) or 0),
                            "bid": float(row.get("bid", 0) or 0),
                            "ask": float(row.get("ask", 0) or 0),
                            "change": float(row.get("change", 0) or 0),
                            "percentChange": float(row.get("percentChange", 0) or 0),
                            "volume": int(row.get("volume", 0) or 0),
                            "openInterest": int(row.get("openInterest", 0) or 0),
                            "impliedVolatility": float(row.get("impliedVolatility", 0) or 0),
                            "inTheMoney": bool(row.get("inTheMoney", False)),
                        })
                    return records

                return {
                    "symbol": symbol.upper(),
                    "expiry": expiry,
                    "calls": df_to_list(chain.calls),
                    "puts": df_to_list(chain.puts),
                }

            return await self._run_sync(_fetch)
        except Exception as exc:
            logger.error("yfinance options chain error for %s %s: %s", symbol, expiry, exc)
            return {"symbol": symbol.upper(), "expiry": expiry, "calls": [], "puts": [], "error": str(exc)}

    async def get_correlation_matrix(self, symbols: list[str], period: str = "3mo") -> dict[str, Any]:
        try:
            import yfinance as yf  # type: ignore
            import pandas as pd  # type: ignore  # noqa: F401 — imported for side effects on yf.download output

            def _fetch() -> dict[str, Any]:
                # Download all symbols at once
                data = yf.download(
                    " ".join(symbols),
                    period=period,
                    auto_adjust=True,
                    progress=False,
                )
                if data.empty:
                    return {"symbols": symbols, "matrix": [], "error": "No data"}

                # Get Close prices
                if len(symbols) == 1:
                    closes = data[["Close"]].rename(columns={"Close": symbols[0]})
                else:
                    closes = data["Close"] if "Close" in data.columns else data.xs("Close", axis=1, level=0)

                # Compute pct returns then correlation
                returns = closes.pct_change().dropna()
                corr = returns.corr()

                sym_list = [s for s in symbols if s in corr.columns]
                matrix = [[round(float(corr.loc[r, c]), 4) for c in sym_list] for r in sym_list]

                return {
                    "symbols": sym_list,
                    "matrix": matrix,
                    "period": period,
                }

            return await self._run_sync(_fetch)
        except Exception as exc:
            logger.error("yfinance correlation error: %s", exc)
            return {"symbols": symbols, "matrix": [], "error": str(exc)}


__all__ = ["YFinanceMarketDataAdapter"]

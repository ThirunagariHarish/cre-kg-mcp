"""Market data endpoints."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from ...adapters.market_data_yfinance import YFinanceMarketDataAdapter
from ..dependencies import get_market_data_adapter, CurrentUser

router = APIRouter(prefix="/api/market", tags=["market-data"])


@router.get("/search", summary="Search for symbols")
async def search_symbols(
    q: str,
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
) -> list[dict[str, Any]]:
    """Search for ticker symbols."""
    return await adapter.search_symbols(q)


@router.get("/quote/{symbol}", summary="Get current quote")
async def get_quote(
    symbol: str,
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
) -> dict[str, Any]:
    """Get live quote for a single symbol."""
    return await adapter.get_quote(symbol.upper())


@router.get("/quotes", summary="Get quotes for multiple symbols")
async def get_quotes(
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
    symbols: str = Query(..., description="Comma-separated symbols, e.g. AAPL,NVDA,TSLA"),
) -> dict[str, Any]:
    """Get live quotes for multiple symbols (comma-separated)."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if len(symbol_list) > 50:
        raise HTTPException(status_code=400, detail="Max 50 symbols per request")
    return await adapter.get_quotes(symbol_list)


@router.get("/ohlcv/{symbol}", summary="Get OHLCV bars")
async def get_ohlcv(
    symbol: str,
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    period: str = Query("1d", description="Time period: 1d, 5d, 1mo, 3mo, 1y"),
    interval: str = Query("1m", description="Bar interval: 1m, 5m, 15m, 1h, 1d"),
) -> dict[str, Any]:
    bars = await adapter.get_ohlcv(symbol.upper(), period=period, interval=interval)
    return {"symbol": symbol.upper(), "bars": bars, "count": len(bars)}


@router.get("/fundamentals/{symbol}", summary="Get fundamental data")
async def get_fundamentals(
    symbol: str,
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
) -> dict[str, Any]:
    return await adapter.get_fundamentals(symbol.upper())


@router.get("/news", summary="Fetch recent news for symbols")
async def get_market_news(
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
    symbols: str = Query("SPY,QQQ,AAPL,NVDA,TSLA,AMD,META,GOOGL,AMZN,MSFT", description="Comma-separated symbols"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Fetch recent news articles for one or more symbols."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return await adapter.get_news(symbol_list, limit)


@router.get("/short-interest/{symbol}", summary="Get short interest data for a symbol")
async def get_short_interest(
    symbol: str,
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
) -> dict[str, Any]:
    """Fetch short interest metrics for a single symbol."""
    return await adapter.get_short_interest(symbol.upper())


@router.get("/indices", summary="Get major index quotes")
async def get_indices(
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
) -> dict[str, Any]:
    """Convenience alias — returns SPY, QQQ, DIA, and ^VIX quotes."""
    return await adapter.get_quotes(["SPY", "QQQ", "DIA", "^VIX"])


@router.get("/options/{symbol}/expiries", summary="Get available options expiry dates")
async def get_options_expiries(
    symbol: str,
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
) -> list[str]:
    return await adapter.get_options_expiries(symbol.upper())


@router.get("/options/{symbol}/chain", summary="Get options chain for symbol and expiry")
async def get_options_chain(
    symbol: str,
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
    expiry: str = Query(..., description="Expiry date string, e.g. 2025-06-20"),
) -> dict[str, Any]:
    return await adapter.get_options_chain(symbol.upper(), expiry)


@router.get("/correlation", summary="Get correlation matrix for a set of symbols")
async def get_correlation(
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
    symbols: str = Query("AAPL,NVDA,TSLA,META,SPY", description="Comma-separated symbols"),
    period: str = Query("3mo", description="Period: 1mo, 3mo, 6mo, 1y"),
) -> dict[str, Any]:
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:15]
    return await adapter.get_correlation_matrix(sym_list, period)


@router.get("/options/{symbol}/iv-term", summary="Get IV term structure (ATM IV per expiry)")
async def get_iv_term_structure(
    symbol: str,
    adapter: Annotated[YFinanceMarketDataAdapter, Depends(get_market_data_adapter)],
    _: CurrentUser,
) -> list[dict[str, Any]]:
    """Returns ATM implied volatility for each available expiry date."""
    expiries = await adapter.get_options_expiries(symbol.upper())
    if not expiries:
        return []

    # Limit to first 8 expiries to keep response fast
    limited = expiries[:8]
    result = []

    quote = await adapter.get_quote(symbol.upper())
    spot = quote.get("price") or 0.0

    for expiry in limited:
        chain_data = await adapter.get_options_chain(symbol.upper(), expiry)
        calls = chain_data.get("calls", [])
        if not calls or not spot:
            continue
        # Find ATM strike (closest to spot)
        atm = min(calls, key=lambda c: abs(c["strike"] - spot), default=None)
        if atm:
            result.append({
                "expiry": expiry,
                "iv": round(atm["impliedVolatility"] * 100, 2),  # as %
                "strike": atm["strike"],
            })

    return result

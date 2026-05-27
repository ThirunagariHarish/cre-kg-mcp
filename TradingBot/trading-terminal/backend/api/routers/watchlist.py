"""Watchlist management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..dependencies import CurrentUser

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# In-memory watchlist store — 10 default symbols
_watchlist: list[dict[str, Any]] = [
    {"symbol": "AAPL", "name": "Apple Inc.", "group": "Tech", "addedAt": _now_iso()},
    {"symbol": "NVDA", "name": "NVIDIA Corp.", "group": "Tech", "addedAt": _now_iso()},
    {"symbol": "MSFT", "name": "Microsoft Corp.", "group": "Tech", "addedAt": _now_iso()},
    {"symbol": "TSLA", "name": "Tesla Inc.", "group": "EV", "addedAt": _now_iso()},
    {"symbol": "AMD", "name": "Advanced Micro Devices", "group": "Tech", "addedAt": _now_iso()},
    {"symbol": "META", "name": "Meta Platforms Inc.", "group": "Tech", "addedAt": _now_iso()},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "group": "Tech", "addedAt": _now_iso()},
    {"symbol": "AMZN", "name": "Amazon.com Inc.", "group": "Tech", "addedAt": _now_iso()},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "group": "ETF", "addedAt": _now_iso()},
    {"symbol": "QQQ", "name": "Invesco QQQ ETF", "group": "ETF", "addedAt": _now_iso()},
]


class AddWatchlistRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    name: str = ""
    group: str = "default"


@router.get("/", summary="Get watchlist")
async def get_watchlist(_: CurrentUser) -> list[dict[str, Any]]:
    return _watchlist


@router.post("/", status_code=201, summary="Add symbol to watchlist")
async def add_to_watchlist(
    body: AddWatchlistRequest,
    _: CurrentUser,
) -> dict[str, Any]:
    symbol = body.symbol.upper().strip()
    # Check duplicate
    if any(w["symbol"] == symbol for w in _watchlist):
        raise HTTPException(status_code=409, detail=f"Symbol {symbol} already in watchlist")
    entry: dict[str, Any] = {
        "symbol": symbol,
        "name": body.name or symbol,
        "group": body.group,
        "addedAt": _now_iso(),
    }
    _watchlist.append(entry)
    return entry


@router.delete("/{symbol}", summary="Remove symbol from watchlist")
async def remove_from_watchlist(
    symbol: str,
    _: CurrentUser,
) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    global _watchlist
    before = len(_watchlist)
    _watchlist = [w for w in _watchlist if w["symbol"] != symbol]
    if len(_watchlist) == before:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not in watchlist")
    return {"symbol": symbol, "removed": True}


__all__ = ["router"]

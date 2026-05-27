"""Position and portfolio endpoints."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...services.portfolio_service import PortfolioService
from ..dependencies import get_portfolio_service, CurrentUser

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/summary", summary="Get portfolio summary")
async def portfolio_summary(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    _: CurrentUser,
) -> dict[str, Any]:
    """Get full portfolio summary including cash, positions, unrealized P&L."""
    return await service.get_summary()


@router.get("/equity-curve", summary="Get equity curve data")
async def equity_curve(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    _: CurrentUser,
    range: str = Query("1D", description="Time range: 1D, 1W, 1M, 3M, 1Y"),
) -> list[dict[str, Any]]:
    """Get NAV equity curve data points."""
    return await service.get_equity_curve(range=range)


@router.get("/positions", summary="Get open positions")
async def list_positions(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    _: CurrentUser,
) -> list[dict[str, Any]]:
    """Get all open positions."""
    positions = await service.get_positions()
    return [p.model_dump() for p in positions]


@router.get("/", summary="Get portfolio snapshot")
async def get_portfolio(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> dict[str, Any]:
    return await service.get_portfolio_snapshot()


@router.post("/prices", summary="Batch update position prices")
async def update_prices(
    prices: dict[str, float],
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> dict[str, Any]:
    await service.update_prices(prices)
    return {"updated": list(prices.keys()), "count": len(prices)}

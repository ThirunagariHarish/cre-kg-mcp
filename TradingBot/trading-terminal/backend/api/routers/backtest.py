"""Backtest API endpoints."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from ..dependencies import CurrentUser
from ...services.backtest_engine import (
    run_backtest, run_all_backtests, get_cached_rankings, STRATEGY_MAP
)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.get("/rankings", summary="Get agent rankings by backtest performance")
async def get_rankings(_: CurrentUser) -> list[dict[str, Any]]:
    results = await get_cached_rankings()
    return [
        {
            "rank": i + 1,
            "agent_id": m.agent_id,
            "total_return_pct": m.total_return_pct,
            "sharpe_ratio": m.sharpe_ratio,
            "sortino_ratio": m.sortino_ratio,
            "max_drawdown_pct": m.max_drawdown_pct,
            "win_rate": round(m.win_rate * 100, 1),
            "profit_factor": m.profit_factor,
            "calmar_ratio": m.calmar_ratio,
            "total_trades": m.total_trades,
            "ranking_score": m.ranking_score,
        }
        for i, m in enumerate(results)
    ]


@router.get("/{agent_id}/results", summary="Get detailed backtest for one agent")
async def get_agent_results(agent_id: str, _: CurrentUser, period: str = Query("2y")) -> dict[str, Any]:
    if agent_id not in STRATEGY_MAP:
        raise HTTPException(status_code=404, detail=f"No backtest strategy for agent: {agent_id}")
    metrics = await run_backtest(agent_id, period=period)
    if not metrics:
        raise HTTPException(status_code=500, detail="Backtest failed")
    return {
        "agent_id": metrics.agent_id,
        "total_return_pct": metrics.total_return_pct,
        "sharpe_ratio": metrics.sharpe_ratio,
        "sortino_ratio": metrics.sortino_ratio,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "win_rate": round(metrics.win_rate * 100, 1),
        "profit_factor": metrics.profit_factor,
        "calmar_ratio": metrics.calmar_ratio,
        "total_trades": metrics.total_trades,
        "winning_trades": metrics.winning_trades,
        "losing_trades": metrics.losing_trades,
        "avg_hold_days": metrics.avg_hold_days,
        "ranking_score": metrics.ranking_score,
        "equity_curve": metrics.equity_curve,
        "trades": [
            {
                "symbol": t.symbol,
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct,
                "hold_days": t.hold_days,
                "exit_reason": t.exit_reason,
            }
            for t in metrics.trades[:100]
        ],
    }


@router.post("/run", summary="Trigger a backtest run for all agents")
async def trigger_backtest(background_tasks: BackgroundTasks, _: CurrentUser) -> dict[str, Any]:
    async def _run() -> None:
        import backend.services.backtest_engine as be
        be._backtest_cache = await run_all_backtests()
        from datetime import datetime, timezone
        be._backtest_last_run = datetime.now(timezone.utc)

    background_tasks.add_task(_run)
    return {"status": "backtest_triggered", "agents": list(STRATEGY_MAP.keys())}


__all__ = ["router"]

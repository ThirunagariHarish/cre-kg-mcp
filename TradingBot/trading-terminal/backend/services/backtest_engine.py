"""Backtesting engine — runs strategy signals against historical OHLCV data.

Uses vectorized pandas operations for speed.
Supports: breakout, VCP, darkpool followthrough, earnings momentum, gap & go, iron condor.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    agent_id: str
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    direction: str  # "long" | "short"
    pnl: float
    pnl_pct: float
    hold_days: int
    exit_reason: str  # "TAKE_PROFIT" | "STOP_LOSS" | "TIME_EXIT"


@dataclass
class BacktestMetrics:
    agent_id: str
    symbol: str
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    calmar_ratio: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_hold_days: float
    ranking_score: float
    equity_curve: list[dict[str, Any]]  # [{date, value}]
    trades: list[BacktestTrade]


def _compute_metrics(
    agent_id: str,
    symbol: str,
    trades: list[BacktestTrade],
    initial_capital: float = 10_000.0,
) -> BacktestMetrics:
    if not trades:
        return BacktestMetrics(
            agent_id=agent_id, symbol=symbol,
            total_return_pct=0, sharpe_ratio=0, sortino_ratio=0,
            max_drawdown_pct=0, win_rate=0, profit_factor=0, calmar_ratio=0,
            total_trades=0, winning_trades=0, losing_trades=0, avg_hold_days=0,
            ranking_score=0, equity_curve=[], trades=[],
        )

    pnl_pcts = [t.pnl_pct for t in trades]
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    win_rate = len(wins) / len(trades)
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Equity curve
    equity = initial_capital
    equity_curve = []
    peak = equity
    max_dd = 0.0
    for t in trades:
        equity += t.pnl
        equity_curve.append({"date": t.exit_date, "value": round(equity, 2)})
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    total_return_pct = (equity - initial_capital) / initial_capital * 100

    # Sharpe (annualized, assuming 252 trading days)
    arr = np.array(pnl_pcts)
    if arr.std() > 0:
        sharpe = (arr.mean() / arr.std()) * np.sqrt(252)
    else:
        sharpe = 0.0

    # Sortino (downside deviation only)
    neg = arr[arr < 0]
    down_std = neg.std() if len(neg) > 0 else 0.0
    sortino = (arr.mean() / down_std) * np.sqrt(252) if down_std > 0 else 0.0

    # Calmar
    calmar = total_return_pct / max_dd if max_dd > 0 else 0.0

    avg_hold = sum(t.hold_days for t in trades) / len(trades)

    # Composite ranking score
    def _norm(v: float, lo: float = 0, hi: float = 1) -> float:
        if hi == lo:
            return 0.5
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    score = (
        0.30 * _norm(sharpe, -1, 3) +
        0.20 * _norm(total_return_pct, -50, 200) +
        0.20 * _norm(win_rate, 0.3, 0.8) +
        0.15 * _norm(-max_dd, -100, 0) +
        0.15 * _norm(min(profit_factor, 5), 0, 5)
    )

    return BacktestMetrics(
        agent_id=agent_id, symbol=symbol,
        total_return_pct=round(total_return_pct, 2),
        sharpe_ratio=round(sharpe, 3),
        sortino_ratio=round(sortino, 3),
        max_drawdown_pct=round(max_dd, 2),
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 3),
        calmar_ratio=round(calmar, 3),
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        avg_hold_days=round(avg_hold, 1),
        ranking_score=round(score, 4),
        equity_curve=equity_curve,
        trades=trades,
    )


def backtest_breakout_trader(df: pd.DataFrame, symbol: str) -> list[BacktestTrade]:
    """
    Breakout Trader: Enter when close > 20-day high AND volume > 1.5x avg.
    Exit: +15% take profit OR -8% stop loss OR 20 days.
    """
    if len(df) < 25:
        return []
    df = df.copy()
    df["high20"] = df["Close"].shift(1).rolling(20).max()
    df["vol_avg"] = df["Volume"].rolling(20).mean()
    df["signal"] = (df["Close"] > df["high20"]) & (df["Volume"] > df["vol_avg"] * 1.5)

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_date = ""
    entry_idx = 0

    for i, row in df.iterrows():
        idx = df.index.get_loc(i)
        if not in_trade and row["signal"]:
            in_trade = True
            entry_price = float(row["Close"])
            entry_date = str(i)[:10]
            entry_idx = idx
        elif in_trade:
            current = float(row["Close"])
            hold = idx - entry_idx
            chg_pct = (current - entry_price) / entry_price * 100
            reason = None
            if chg_pct >= 15.0:
                reason = "TAKE_PROFIT"
            elif chg_pct <= -8.0:
                reason = "STOP_LOSS"
            elif hold >= 20:
                reason = "TIME_EXIT"
            if reason:
                trades.append(BacktestTrade(
                    agent_id="breakout_trader", symbol=symbol,
                    entry_date=entry_date, exit_date=str(i)[:10],
                    entry_price=entry_price, exit_price=current,
                    direction="long", pnl=(current - entry_price) * 100,
                    pnl_pct=chg_pct, hold_days=hold, exit_reason=reason,
                ))
                in_trade = False
    return trades


def backtest_gap_executor(df: pd.DataFrame, symbol: str) -> list[BacktestTrade]:
    """
    Gap & Go: Enter on open if gap > 2% from prev close.
    Exit at end of day.
    """
    if len(df) < 5:
        return []
    df = df.copy()
    df["prev_close"] = df["Close"].shift(1)
    df["gap_pct"] = (df["Open"] - df["prev_close"]) / df["prev_close"] * 100

    trades = []
    for i, row in df.iterrows():
        if abs(row["gap_pct"]) < 2.0:
            continue
        direction = "long" if row["gap_pct"] > 0 else "short"
        entry = float(row["Open"])
        exit_p = float(row["Close"])
        if direction == "long":
            pnl_pct = (exit_p - entry) / entry * 100
        else:
            pnl_pct = (entry - exit_p) / entry * 100
        trades.append(BacktestTrade(
            agent_id="gap_executor", symbol=symbol,
            entry_date=str(i)[:10], exit_date=str(i)[:10],
            entry_price=entry, exit_price=exit_p,
            direction=direction, pnl=pnl_pct * 100,
            pnl_pct=pnl_pct, hold_days=1, exit_reason="TIME_EXIT",
        ))
    return trades


def backtest_vcp_trader(df: pd.DataFrame, symbol: str) -> list[BacktestTrade]:
    """
    VCP: Volatility contraction + range narrowing over 3 weeks + volume dry-up.
    Enter on breakout above last 3-week high with lower volume than prior week.
    """
    if len(df) < 30:
        return []
    df = df.copy()
    df["wk_range"] = df["High"].rolling(5).max() - df["Low"].rolling(5).min()
    df["wk_vol"] = df["Volume"].rolling(5).mean()
    df["contracting"] = (
        (df["wk_range"] < df["wk_range"].shift(5)) &
        (df["wk_range"].shift(5) < df["wk_range"].shift(10)) &
        (df["wk_vol"] < df["wk_vol"].shift(5))
    )
    df["pivot"] = df["High"].rolling(15).max().shift(1)
    df["signal"] = df["contracting"] & (df["Close"] > df["pivot"])

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_date = ""
    entry_idx = 0

    for i, row in df.iterrows():
        idx = df.index.get_loc(i)
        if not in_trade and row["signal"]:
            in_trade = True
            entry_price = float(row["Close"])
            entry_date = str(i)[:10]
            entry_idx = idx
        elif in_trade:
            current = float(row["Close"])
            hold = idx - entry_idx
            chg_pct = (current - entry_price) / entry_price * 100
            reason = None
            if chg_pct >= 20.0:
                reason = "TAKE_PROFIT"
            elif chg_pct <= -7.0:
                reason = "STOP_LOSS"
            elif hold >= 30:
                reason = "TIME_EXIT"
            if reason:
                trades.append(BacktestTrade(
                    agent_id="vcp_setups_trader", symbol=symbol,
                    entry_date=entry_date, exit_date=str(i)[:10],
                    entry_price=entry_price, exit_price=current,
                    direction="long", pnl=(current - entry_price) * 100,
                    pnl_pct=chg_pct, hold_days=hold, exit_reason=reason,
                ))
                in_trade = False
    return trades


def backtest_dark_pool(df: pd.DataFrame, symbol: str) -> list[BacktestTrade]:
    """
    Dark Pool: Simulated — enter day+1 after strong volume spike (proxy for dark pool).
    Volume > 2x avg AND close near high of day = institutional accumulation.
    """
    if len(df) < 20:
        return []
    df = df.copy()
    df["vol_avg"] = df["Volume"].rolling(20).mean()
    df["close_near_high"] = (df["Close"] - df["Low"]) / (df["High"] - df["Low"] + 0.01) > 0.7
    df["signal"] = (df["Volume"] > df["vol_avg"] * 2.0) & df["close_near_high"]
    df["entry_tomorrow"] = df["signal"].shift(1)

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_date = ""
    entry_idx = 0

    for i, row in df.iterrows():
        idx = df.index.get_loc(i)
        if not in_trade and row.get("entry_tomorrow"):
            in_trade = True
            entry_price = float(row["Open"])
            entry_date = str(i)[:10]
            entry_idx = idx
        elif in_trade:
            current = float(row["Close"])
            hold = idx - entry_idx
            chg_pct = (current - entry_price) / entry_price * 100
            reason = None
            if chg_pct >= 10.0:
                reason = "TAKE_PROFIT"
            elif chg_pct <= -6.0:
                reason = "STOP_LOSS"
            elif hold >= 5:
                reason = "TIME_EXIT"
            if reason:
                trades.append(BacktestTrade(
                    agent_id="dark_pool_followthrough", symbol=symbol,
                    entry_date=entry_date, exit_date=str(i)[:10],
                    entry_price=entry_price, exit_price=current,
                    direction="long", pnl=(current - entry_price) * 100,
                    pnl_pct=chg_pct, hold_days=hold, exit_reason=reason,
                ))
                in_trade = False
    return trades


def backtest_earnings_momentum(df: pd.DataFrame, symbol: str) -> list[BacktestTrade]:
    """
    Earnings Momentum: Proxy — large gap on high volume, hold 3 days.
    """
    if len(df) < 10:
        return []
    df = df.copy()
    df["prev_close"] = df["Close"].shift(1)
    df["gap_pct"] = (df["Open"] - df["prev_close"]) / df["prev_close"] * 100
    df["vol_avg"] = df["Volume"].rolling(20).mean()
    df["signal"] = (df["gap_pct"] > 3.0) & (df["Volume"] > df["vol_avg"] * 2.0)

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_date = ""
    entry_idx = 0

    for i, row in df.iterrows():
        idx = df.index.get_loc(i)
        if not in_trade and row["signal"]:
            in_trade = True
            entry_price = float(row["Open"])
            entry_date = str(i)[:10]
            entry_idx = idx
        elif in_trade:
            current = float(row["Close"])
            hold = idx - entry_idx
            chg_pct = (current - entry_price) / entry_price * 100
            reason = None
            if chg_pct >= 12.0:
                reason = "TAKE_PROFIT"
            elif chg_pct <= -8.0:
                reason = "STOP_LOSS"
            elif hold >= 3:
                reason = "TIME_EXIT"
            if reason:
                trades.append(BacktestTrade(
                    agent_id="earnings_momentum", symbol=symbol,
                    entry_date=entry_date, exit_date=str(i)[:10],
                    entry_price=entry_price, exit_price=current,
                    direction="long", pnl=(current - entry_price) * 100,
                    pnl_pct=chg_pct, hold_days=hold, exit_reason=reason,
                ))
                in_trade = False
    return trades


STRATEGY_MAP = {
    "breakout_trader": backtest_breakout_trader,
    "vcp_setups_trader": backtest_vcp_trader,
    "gap_executor": backtest_gap_executor,
    "dark_pool_followthrough": backtest_dark_pool,
    "earnings_momentum": backtest_earnings_momentum,
}

SYMBOLS = ["AAPL", "NVDA", "TSLA", "META", "GOOGL", "AMZN", "SPY", "QQQ", "AMD", "MSFT"]


async def run_backtest(
    agent_id: str,
    symbols: list[str] | None = None,
    period: str = "2y",
    initial_capital: float = 10_000.0,
) -> BacktestMetrics | None:
    """Run a backtest for a single agent across multiple symbols."""
    strategy_fn = STRATEGY_MAP.get(agent_id)
    if not strategy_fn:
        logger.warning("No backtest strategy defined for agent: %s", agent_id)
        return None

    target_symbols = symbols or SYMBOLS
    all_trades: list[BacktestTrade] = []

    def _fetch_and_run(sym: str) -> list[BacktestTrade]:
        try:
            import yfinance as yf  # type: ignore
            df = yf.download(sym, period=period, auto_adjust=True, progress=False)
            if df.empty or len(df) < 30:
                return []
            return strategy_fn(df, sym)
        except Exception as e:
            logger.warning("Backtest data fetch failed for %s: %s", sym, e)
            return []

    loop = asyncio.get_event_loop()
    results = await asyncio.gather(*[
        loop.run_in_executor(None, _fetch_and_run, sym)
        for sym in target_symbols
    ])
    for trades in results:
        all_trades.extend(trades)

    # Sort by entry date
    all_trades.sort(key=lambda t: t.entry_date)

    return _compute_metrics(agent_id, ",".join(target_symbols), all_trades, initial_capital)


async def run_all_backtests(period: str = "2y") -> list[BacktestMetrics]:
    """Run backtests for all agents and return sorted by ranking_score."""
    results = await asyncio.gather(*[
        run_backtest(agent_id, period=period)
        for agent_id in STRATEGY_MAP
    ])
    valid = [r for r in results if r is not None]
    valid.sort(key=lambda m: m.ranking_score, reverse=True)
    return valid


# Cache last results
_backtest_cache: list[BacktestMetrics] = []
_backtest_last_run: datetime | None = None


async def get_cached_rankings() -> list[BacktestMetrics]:
    global _backtest_cache, _backtest_last_run
    now = datetime.now(timezone.utc)
    if not _backtest_cache or _backtest_last_run is None or \
            (now - _backtest_last_run).total_seconds() > 3600:
        _backtest_cache = await run_all_backtests()
        _backtest_last_run = now
    return _backtest_cache


__all__ = ["run_backtest", "run_all_backtests", "get_cached_rankings", "BacktestMetrics", "BacktestTrade"]

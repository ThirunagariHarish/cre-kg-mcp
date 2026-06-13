"""
backtesting/report.py — Human-readable and JSON-serialisable output for BacktestResult.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from backtesting.engine import BacktestResult


def print_report(result: BacktestResult) -> None:
    """Print a formatted summary of the backtest result to stdout."""
    sep = "-" * 52
    print(sep)
    print(f"  Backtest Report — {result.analyst_id}")
    print(sep)
    print(f"  Total trades     : {result.total_trades}")
    print(f"  Winning trades   : {result.winning_trades}")
    print(f"  Losing trades    : {result.losing_trades}")
    print(f"  Win rate         : {result.win_rate:.1%}")
    print(f"  Avg win          : {result.avg_win_pct:.1%}")
    print(f"  Avg loss         : {result.avg_loss_pct:.1%}")
    print(f"  Total P&L        : ${result.total_pnl:,.2f}")
    print(f"  Max drawdown     : {result.max_drawdown_pct:.1%}")
    print(sep)

    if result.trades:
        recent = result.trades[-5:]
        print(f"  Last {len(recent)} trade(s):")
        header = f"  {'Symbol':<8} {'Dir':<5} {'Strike':>7} {'Fill':>6} {'Exit':>6} {'PnL%':>7} {'Reason'}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for t in recent:
            print(
                f"  {t.symbol:<8} {t.direction:<5} {t.strike:>7.1f}"
                f" {t.fill_price:>6.2f} {t.exit_price:>6.2f}"
                f" {t.pnl_pct:>7.1%} {t.exit_reason}"
            )

    print(sep)


def save_report(result: BacktestResult, path: str = "shared/state/backtest_report.json") -> None:
    """Serialise the full BacktestResult to a JSON file."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = dataclasses.asdict(result)
    with open(out_path, "w") as fh:
        json.dump(data, fh, indent=2, default=str)

    print(f"Report saved to {out_path}")

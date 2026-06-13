"""
scripts/run_eod_evaluator.py — Manual / cron trigger for the EOD RL evaluator.

Usage:
    python scripts/run_eod_evaluator.py

Typically scheduled at 4:30 PM ET after market close.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from master.eod_evaluator import EODEvaluator
from master.memory_journal import MemoryJournal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_eod_evaluator")


async def main() -> None:
    journal = MemoryJournal()
    await journal.initialize()

    try:
        evaluator = EODEvaluator(journal)
        report = await evaluator.run_evaluation()

        # ── Print summary ──────────────────────────────────────────────────
        print()
        print("=" * 60)
        print(f"  EOD Evaluation Report — {report.date}")
        print("=" * 60)
        print(f"  Analysts evaluated : {len(report.analysts_evaluated)}")
        print(f"  Changes applied    : {len(report.changes_made)}")
        print(f"  Changes deferred   : {len(report.changes_deferred)}")
        print(f"  Portfolio PnL (7d) : {report.total_pnl:+.4f}")
        print()

        if report.analysts_evaluated:
            print("  Per-analyst stats:")
            for s in sorted(report.analysts_evaluated, key=lambda x: x.win_rate):
                trades_note = (
                    f"{s.total_trades} trades"
                    if s.total_trades >= evaluator.MIN_TRADES_FOR_EVAL
                    else f"{s.total_trades} trades (below eval threshold)"
                )
                print(
                    f"    {s.analyst_id:<20} win_rate={s.win_rate:.2f}  "
                    f"avg_pnl={s.avg_pnl_pct:+.2%}  {trades_note}"
                )
            print()

        if report.changes_made:
            print("  Parameter changes applied:")
            for c in report.changes_made:
                print(
                    f"    {c.analyst_id:<20} {c.parameter:<25} "
                    f"{c.old_value:.4f} -> {c.new_value:.4f}"
                )
                print(f"      reason: {c.reason}")
            print()

        if report.changes_deferred:
            print("  Deferred changes (MAX_CHANGES_PER_EVAL limit reached):")
            for c in report.changes_deferred:
                print(
                    f"    {c.analyst_id:<20} {c.parameter:<25} "
                    f"(would: {c.old_value:.4f} -> {c.new_value:.4f})"
                )
            print()

        print("=" * 60)
        print()

    finally:
        await journal.close()


if __name__ == "__main__":
    asyncio.run(main())

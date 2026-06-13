"""
master/eod_evaluator.py — EOD Evaluator and RL parameter-tuning loop.

Runs at market close (4:30 PM ET) to evaluate analyst performance and tune parameters.
Triggered by cron or run manually via scripts/run_eod_evaluator.py.

RL contract:
  - Reads last 7 days of closed trades from MemoryJournal
  - Groups by analyst_id
  - For each analyst: compute win_rate, avg_pnl, best_pattern, worst_pattern
  - Generate ParameterChanges (max MAX_CHANGES_PER_EVAL total)
  - Apply changes within hard limits (confidence_threshold 0.50–0.90, max_premium_usd $100–$500)
  - NEVER auto-change: position sizing, live/paper mode, kill switch
  - Write report to shared/state/rl/evaluations.json
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from master.memory_journal import MemoryJournal

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Hard limits — these values MUST NOT be violated even under RL pressure
# ─────────────────────────────────────────────

_CONFIDENCE_MIN = 0.50
_CONFIDENCE_MAX = 0.90
_CONFIDENCE_STEP = 0.05

_PREMIUM_MIN_USD = 100.0
_PREMIUM_MAX_USD = 500.0
_PREMIUM_STEP_USD = 50.0

# Parameters that are NEVER auto-changed
_FORBIDDEN_PARAMS = frozenset({
    "max_position_size_usd",
    "position_size_usd",
    "position_sizing",
    "paper_mode",
    "live_mode",
    "kill_switch",
    "max_daily_loss",
    "pdt_limit",
})

# ─────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────

@dataclass
class AnalystStats:
    analyst_id: str
    total_trades: int
    win_rate: float
    avg_pnl_pct: float
    worst_pattern: str | None
    best_pattern: str | None


@dataclass
class ParameterChange:
    analyst_id: str
    parameter: str
    old_value: float
    new_value: float
    reason: str


@dataclass
class EvalReport:
    date: str
    analysts_evaluated: list[AnalystStats]
    changes_made: list[ParameterChange]
    changes_deferred: list[ParameterChange]  # exceeded max_changes or hit hard limits
    total_pnl: float


# ─────────────────────────────────────────────
# EODEvaluator
# ─────────────────────────────────────────────

class EODEvaluator:
    """
    End-of-day RL evaluator.

    Reads recent closed trades from MemoryJournal, computes per-analyst
    performance stats, proposes parameter changes, applies them within
    hard limits, and writes a report to shared/state/rl/evaluations.json.
    """

    MAX_CHANGES_PER_EVAL = 3
    MIN_WIN_RATE_THRESHOLD = 0.40
    MIN_TRADES_FOR_EVAL = 5

    def __init__(
        self,
        journal: MemoryJournal,
        configs_dir: str = "configs/analysts",
        report_path: str = "shared/state/rl/evaluations.json",
    ) -> None:
        self.journal = journal
        self.configs_dir = Path(configs_dir)
        self.report_path = Path(report_path)

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    async def run_evaluation(self) -> EvalReport:
        """
        Full evaluation cycle:
          1. Load recent trades
          2. Compute per-analyst stats
          3. Generate candidate parameter changes
          4. Apply changes within limits and MAX_CHANGES_PER_EVAL cap
          5. Write report to disk
          6. Return EvalReport
        """
        today = date.today().isoformat()
        logger.info("EOD evaluation started for %s", today)

        # 1. Discover analyst IDs from config files (fallback to trades)
        analyst_ids = self._discover_analyst_ids()

        # 2. Compute stats for each analyst
        all_stats: list[AnalystStats] = []
        for aid in analyst_ids:
            stats = await self._compute_analyst_stats(aid)
            all_stats.append(stats)
            logger.debug(
                "Analyst %s: %d trades, win_rate=%.2f, avg_pnl=%.2f%%",
                aid,
                stats.total_trades,
                stats.win_rate,
                stats.avg_pnl_pct * 100,
            )

        # 3. Generate candidate changes (sorted by priority — worst performers first)
        candidates = await self._generate_parameter_changes(all_stats)

        # 4. Split into applied vs deferred
        changes_made: list[ParameterChange] = []
        changes_deferred: list[ParameterChange] = []

        for change in candidates:
            if len(changes_made) < self.MAX_CHANGES_PER_EVAL:
                changes_made.append(change)
            else:
                changes_deferred.append(change)

        # 5. Apply accepted changes
        if changes_made:
            await self._apply_changes(changes_made)

        # 6. Compute total PnL across all analysts
        total_pnl = sum(
            s.avg_pnl_pct * s.total_trades
            for s in all_stats
            if s.total_trades > 0
        )

        report = EvalReport(
            date=today,
            analysts_evaluated=all_stats,
            changes_made=changes_made,
            changes_deferred=changes_deferred,
            total_pnl=total_pnl,
        )

        self._write_report(report)
        logger.info(
            "EOD evaluation complete: %d analysts, %d changes applied, %d deferred",
            len(all_stats),
            len(changes_made),
            len(changes_deferred),
        )
        return report

    # ──────────────────────────────────────────
    # Stats computation
    # ──────────────────────────────────────────

    async def _compute_analyst_stats(self, analyst_id: str) -> AnalystStats:
        """
        Compute win_rate, avg_pnl_pct, best/worst patterns for one analyst
        using data from the last 7 days.
        """
        trades = await self.journal.get_recent_trades(analyst_id, days=7)

        if not trades:
            return AnalystStats(
                analyst_id=analyst_id,
                total_trades=0,
                win_rate=0.0,
                avg_pnl_pct=0.0,
                worst_pattern=None,
                best_pattern=None,
            )

        # Aggregate per-pattern
        pattern_wins: dict[str, int] = {}
        pattern_losses: dict[str, int] = {}
        pattern_pnl: dict[str, float] = {}

        wins = 0
        losses = 0
        total_pnl = 0.0

        for trade in trades:
            outcome = trade.get("outcome", "")
            pnl_pct = trade.get("pnl_pct", 0.0) or 0.0
            pattern = trade.get("market_conditions")  # may be a JSON string
            # Derive pattern from trade row columns
            symbol = trade.get("symbol", "UNKNOWN")
            direction = trade.get("direction", "UNKNOWN")
            # We don't have time_label per row, use a generic pattern
            pat = f"{symbol}_{direction}"

            pattern_pnl[pat] = pattern_pnl.get(pat, 0.0) + pnl_pct

            if outcome == "WIN":
                wins += 1
                pattern_wins[pat] = pattern_wins.get(pat, 0) + 1
            elif outcome == "LOSS":
                losses += 1
                pattern_losses[pat] = pattern_losses.get(pat, 0) + 1

            total_pnl += pnl_pct

        total_decided = wins + losses
        win_rate = (wins / total_decided) if total_decided > 0 else 0.0
        avg_pnl_pct = (total_pnl / len(trades)) if trades else 0.0

        # Best pattern: highest avg pnl
        all_patterns = set(pattern_pnl.keys())
        best_pattern: str | None = None
        worst_pattern: str | None = None

        if all_patterns:
            best_pattern = max(all_patterns, key=lambda p: pattern_pnl[p])
            worst_pattern = min(all_patterns, key=lambda p: pattern_pnl[p])
            # If best == worst (only one pattern), keep it meaningful
            if best_pattern == worst_pattern:
                worst_pattern = best_pattern

        return AnalystStats(
            analyst_id=analyst_id,
            total_trades=len(trades),
            win_rate=win_rate,
            avg_pnl_pct=avg_pnl_pct,
            worst_pattern=worst_pattern,
            best_pattern=best_pattern,
        )

    # ──────────────────────────────────────────
    # Parameter change generation
    # ──────────────────────────────────────────

    async def _generate_parameter_changes(
        self, stats: list[AnalystStats]
    ) -> list[ParameterChange]:
        """
        Inspect per-analyst performance and propose parameter changes.

        Rules:
          - Only analysts with >= MIN_TRADES_FOR_EVAL trades are considered.
          - win_rate < MIN_WIN_RATE_THRESHOLD → raise confidence_threshold by +0.05
            (forces the analyst to only take higher-conviction trades)
          - win_rate > 0.65 AND avg_pnl_pct > 0 → lower confidence_threshold by -0.05
            (loosening entry filter when performance is strong)
          - avg_pnl_pct < -0.10 → reduce max_premium_usd by -$50
            (cut capital exposure when losing big)
          - avg_pnl_pct > 0.15 → increase max_premium_usd by +$50
            (allow larger positions when consistently winning)

        All proposed changes are validated against hard limits.
        Returns changes sorted by urgency (worst performers first).
        """
        changes: list[ParameterChange] = []

        # Sort by win_rate ascending so worst performers get priority
        sorted_stats = sorted(stats, key=lambda s: s.win_rate)

        for s in sorted_stats:
            if s.total_trades < self.MIN_TRADES_FOR_EVAL:
                logger.debug(
                    "Skipping %s: only %d trades (need %d)",
                    s.analyst_id,
                    s.total_trades,
                    self.MIN_TRADES_FOR_EVAL,
                )
                continue

            config = self._load_analyst_config(s.analyst_id)

            # -- confidence_threshold --
            current_confidence = float(config.get("confidence_threshold", 0.65))
            confidence_change = self._propose_confidence_change(s, current_confidence)
            if confidence_change is not None:
                changes.append(confidence_change)

            # -- max_premium_usd --
            current_premium = float(config.get("max_premium_usd", 300.0))
            premium_change = self._propose_premium_change(s, current_premium)
            if premium_change is not None:
                changes.append(premium_change)

        return changes

    def _propose_confidence_change(
        self, s: AnalystStats, current: float
    ) -> ParameterChange | None:
        """Propose a confidence_threshold adjustment, or None if no change needed."""
        if s.win_rate < self.MIN_WIN_RATE_THRESHOLD:
            # Poor performance → raise the bar
            new_val = round(current + _CONFIDENCE_STEP, 10)
            new_val = min(new_val, _CONFIDENCE_MAX)
            if new_val == current:
                return None  # already at ceiling
            return ParameterChange(
                analyst_id=s.analyst_id,
                parameter="confidence_threshold",
                old_value=current,
                new_value=new_val,
                reason=(
                    f"win_rate={s.win_rate:.2f} below threshold "
                    f"{self.MIN_WIN_RATE_THRESHOLD:.2f}; raising confidence bar"
                ),
            )

        if s.win_rate > 0.65 and s.avg_pnl_pct > 0:
            # Strong performance → loosen entry filter slightly
            new_val = round(current - _CONFIDENCE_STEP, 10)
            new_val = max(new_val, _CONFIDENCE_MIN)
            if new_val == current:
                return None  # already at floor
            return ParameterChange(
                analyst_id=s.analyst_id,
                parameter="confidence_threshold",
                old_value=current,
                new_value=new_val,
                reason=(
                    f"win_rate={s.win_rate:.2f} strong, avg_pnl={s.avg_pnl_pct:.2%}; "
                    "lowering confidence threshold to capture more signals"
                ),
            )

        return None

    def _propose_premium_change(
        self, s: AnalystStats, current: float
    ) -> ParameterChange | None:
        """Propose a max_premium_usd adjustment, or None if no change needed."""
        if s.avg_pnl_pct < -0.10:
            new_val = current - _PREMIUM_STEP_USD
            new_val = max(new_val, _PREMIUM_MIN_USD)
            if new_val == current:
                return None
            return ParameterChange(
                analyst_id=s.analyst_id,
                parameter="max_premium_usd",
                old_value=current,
                new_value=new_val,
                reason=(
                    f"avg_pnl={s.avg_pnl_pct:.2%} below -10%; "
                    "reducing max premium to limit losses"
                ),
            )

        if s.avg_pnl_pct > 0.15 and s.win_rate > 0.50:
            new_val = current + _PREMIUM_STEP_USD
            new_val = min(new_val, _PREMIUM_MAX_USD)
            if new_val == current:
                return None
            return ParameterChange(
                analyst_id=s.analyst_id,
                parameter="max_premium_usd",
                old_value=current,
                new_value=new_val,
                reason=(
                    f"avg_pnl={s.avg_pnl_pct:.2%} above 15%, win_rate={s.win_rate:.2f}; "
                    "increasing max premium to scale gains"
                ),
            )

        return None

    # ──────────────────────────────────────────
    # Apply changes
    # ──────────────────────────────────────────

    async def _apply_changes(self, changes: list[ParameterChange]) -> None:
        """
        Write each accepted ParameterChange back to configs/analysts/{analyst_id}.json.
        Uses a temp-file + atomic rename to avoid partial writes.
        """
        for change in changes:
            # Safety gate: never touch forbidden parameters
            if change.parameter in _FORBIDDEN_PARAMS:
                logger.error(
                    "RL: BLOCKED attempt to change forbidden param %s for %s",
                    change.parameter,
                    change.analyst_id,
                )
                continue

            # Hard-limit guard (belt-and-suspenders)
            clamped = self._clamp_value(change.parameter, change.new_value)
            if clamped != change.new_value:
                logger.warning(
                    "RL: %s %s clamped %s -> %s (hard limit)",
                    change.analyst_id,
                    change.parameter,
                    change.new_value,
                    clamped,
                )
                change = ParameterChange(
                    analyst_id=change.analyst_id,
                    parameter=change.parameter,
                    old_value=change.old_value,
                    new_value=clamped,
                    reason=change.reason + " [clamped to hard limit]",
                )

            config = self._load_analyst_config(change.analyst_id)
            config[change.parameter] = change.new_value
            self._save_analyst_config(change.analyst_id, config)

            logger.info(
                "RL: %s %s %.4f -> %.4f | %s",
                change.analyst_id,
                change.parameter,
                change.old_value,
                change.new_value,
                change.reason,
            )

    # ──────────────────────────────────────────
    # Config I/O
    # ──────────────────────────────────────────

    def _discover_analyst_ids(self) -> list[str]:
        """Return analyst IDs from configs/analysts/*.json (excluding mag7_watchlist)."""
        if not self.configs_dir.exists():
            return []
        return [
            p.stem
            for p in sorted(self.configs_dir.glob("*.json"))
            if not p.stem.endswith("_watchlist")
        ]

    def _load_analyst_config(self, analyst_id: str) -> dict:
        """Load configs/analysts/{analyst_id}.json; return {} if not found."""
        path = self.configs_dir / f"{analyst_id}.json"
        if not path.exists():
            logger.debug("Config not found for %s at %s", analyst_id, path)
            return {}
        with path.open() as f:
            return json.load(f)

    def _save_analyst_config(self, analyst_id: str, config: dict) -> None:
        """Atomically write config dict to configs/analysts/{analyst_id}.json."""
        path = self.configs_dir / f"{analyst_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to a temp file in the same dir, then rename
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(config, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, str(path))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ──────────────────────────────────────────
    # Hard-limit enforcement
    # ──────────────────────────────────────────

    @staticmethod
    def _clamp_value(parameter: str, value: float) -> float:
        """Clamp value to hard limits for known parameters."""
        if parameter == "confidence_threshold":
            return max(_CONFIDENCE_MIN, min(_CONFIDENCE_MAX, value))
        if parameter == "max_premium_usd":
            return max(_PREMIUM_MIN_USD, min(_PREMIUM_MAX_USD, value))
        return value

    # ──────────────────────────────────────────
    # Report persistence
    # ──────────────────────────────────────────

    def _write_report(self, report: EvalReport) -> None:
        """Write EvalReport to shared/state/rl/evaluations.json (append mode)."""
        self.report_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialise dataclasses to plain dicts
        def _serialise_change(c: ParameterChange) -> dict:
            return asdict(c)

        def _serialise_stats(s: AnalystStats) -> dict:
            return asdict(s)

        record = {
            "date": report.date,
            "total_pnl": report.total_pnl,
            "analysts_evaluated": [_serialise_stats(s) for s in report.analysts_evaluated],
            "changes_made": [_serialise_change(c) for c in report.changes_made],
            "changes_deferred": [_serialise_change(c) for c in report.changes_deferred],
        }

        # Load existing evaluations and append
        existing: list[dict] = []
        if self.report_path.exists():
            try:
                with self.report_path.open() as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    existing = [existing]
            except (json.JSONDecodeError, ValueError):
                logger.warning("Could not parse existing evaluations.json; overwriting.")
                existing = []

        existing.append(record)

        # Atomic write
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.report_path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(existing, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, str(self.report_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info("RL report written to %s", self.report_path)

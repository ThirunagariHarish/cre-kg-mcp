"""
gateway/monitor_rules.py — M5.3 Monitor Agent RL Rule Tuner

Reads shared/state/monitor_rl_data.jsonl (written by MonitorAgent._close_position),
groups entries by analyst_id + exit_strategy, computes optimal hold timing
and TA disagreement actions, and emits updated rules to monitor_rules.json.

Rules stay within hard limits so they cannot override safety controls.
"""

from __future__ import annotations

import json
import logging
import statistics
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Hard limits that rules can never violate
_MIN_HOLD_FLOOR_MINUTES: int = 2       # never exit before 2 minutes
_MAX_HOLD_CEILING_MINUTES: int = 390   # never hold past 6.5 hours (full trading day)
_DEFAULT_MIN_HOLD_MINUTES: int = 5
_DEFAULT_MAX_HOLD_MINUTES: int = 240
_MIN_SAMPLES_REQUIRED: int = 3         # need at least 3 exits to learn


@dataclass
class AnalystRule:
    """Exit rules for one analyst, learned from RL data."""

    analyst_id: str
    min_hold_minutes: int    # do not exit before this time
    max_hold_minutes: int    # force-exit after this time (override strategy)
    ta_disagreement_action: str  # "HOLD" | "ALERT" | "EXIT"
    last_updated: str
    sample_count: int = 0    # how many exits informed this rule


@dataclass
class MonitorRules:
    """Container of per-analyst rules, ready to be serialised."""

    analyst_rules: dict[str, AnalystRule] = field(default_factory=dict)


class MonitorRulesLearner:
    """
    Reads monitor_rl_data.jsonl and tunes per-analyst exit rules.

    Algorithm:
      1. Group all closed-position records by (analyst_id, exit_strategy).
      2. Split each group into "TA agreed" vs "TA disagreed" subsets.
      3. Compare average pnl_pct between the subsets to recommend a
         ta_disagreement_action for each analyst.
      4. Compute optimal hold_duration as the median of winning trades
         (pnl_pct > 0) — if no winners exist, fall back to all-trade median.
      5. Set min_hold_minutes = floor(0.5 * optimal_hold) clamped to hard limits.
         Set max_hold_minutes = ceil(2.0 * optimal_hold) clamped to hard limits.
      6. Write rules to RULES_FILE atomically and return a MonitorRules object.
    """

    RULES_FILE = Path("shared/state/monitor_rules.json")
    RL_DATA_FILE = Path("shared/state/monitor_rl_data.jsonl")

    def learn(self) -> MonitorRules:
        """Run the learning pass and persist updated rules. Returns the new rules."""
        records = self._load_rl_data()
        if not records:
            logger.warning("monitor_rl_data.jsonl is empty — writing default rules")
            rules = MonitorRules()
            self._write_rules(rules)
            return rules

        # Group by analyst_id
        by_analyst: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rec in records:
            analyst_id = rec.get("analyst_id", "unknown")
            by_analyst[analyst_id].append(rec)

        rules = MonitorRules()
        for analyst_id, recs in by_analyst.items():
            rule = self._derive_rule(analyst_id, recs)
            rules.analyst_rules[analyst_id] = rule
            logger.info(
                "Derived rule for %s: min_hold=%dm max_hold=%dm ta_action=%s (n=%d)",
                analyst_id,
                rule.min_hold_minutes,
                rule.max_hold_minutes,
                rule.ta_disagreement_action,
                rule.sample_count,
            )

        self._write_rules(rules)
        return rules

    # ─── Core derivation ────────────────────────────────────────────────────

    def _derive_rule(self, analyst_id: str, recs: list[dict[str, Any]]) -> AnalystRule:
        """Derive an AnalystRule from a list of closed-position records for one analyst."""
        if len(recs) < _MIN_SAMPLES_REQUIRED:
            logger.debug(
                "Only %d samples for %s — using defaults (need %d)",
                len(recs),
                analyst_id,
                _MIN_SAMPLES_REQUIRED,
            )
            return AnalystRule(
                analyst_id=analyst_id,
                min_hold_minutes=_DEFAULT_MIN_HOLD_MINUTES,
                max_hold_minutes=_DEFAULT_MAX_HOLD_MINUTES,
                ta_disagreement_action="HOLD",
                last_updated=datetime.now(tz=timezone.utc).isoformat(),
                sample_count=len(recs),
            )

        # --- Hold duration ---
        hold_durations = [
            r["hold_duration_minutes"]
            for r in recs
            if isinstance(r.get("hold_duration_minutes"), (int, float))
            and r["hold_duration_minutes"] > 0
        ]
        winning_durations = [
            r["hold_duration_minutes"]
            for r in recs
            if isinstance(r.get("hold_duration_minutes"), (int, float))
            and r["hold_duration_minutes"] > 0
            and isinstance(r.get("pnl_pct"), (int, float))
            and r["pnl_pct"] > 0
        ]

        source = winning_durations if len(winning_durations) >= _MIN_SAMPLES_REQUIRED else hold_durations
        if source:
            optimal_hold = statistics.median(source)
        else:
            optimal_hold = float(_DEFAULT_MIN_HOLD_MINUTES)

        raw_min = max(_MIN_HOLD_FLOOR_MINUTES, int(optimal_hold * 0.5))
        raw_max = min(_MAX_HOLD_CEILING_MINUTES, int(optimal_hold * 2.0))

        # Clamp min to the ceiling so it never exceeds max_hold ceiling
        raw_min = min(raw_min, _MAX_HOLD_CEILING_MINUTES)
        # Ensure min < max (both are already clamped; push max up if needed)
        if raw_min >= raw_max:
            raw_max = min(_MAX_HOLD_CEILING_MINUTES, raw_min + 30)
        # Final safety: if both are at the ceiling, min gets a 30-minute buffer below it
        if raw_min >= raw_max:
            raw_min = max(_MIN_HOLD_FLOOR_MINUTES, raw_max - 30)

        min_hold = raw_min
        max_hold = raw_max

        # --- TA disagreement action ---
        ta_disagreement_action = self._derive_ta_action(recs)

        return AnalystRule(
            analyst_id=analyst_id,
            min_hold_minutes=min_hold,
            max_hold_minutes=max_hold,
            ta_disagreement_action=ta_disagreement_action,
            last_updated=datetime.now(tz=timezone.utc).isoformat(),
            sample_count=len(recs),
        )

    def _derive_ta_action(self, recs: list[dict[str, Any]]) -> str:
        """
        Compare average pnl when TA agreed vs disagreed.

        Logic:
          - If TA-agreed trades outperform by >10 pct-points: recommend EXIT on disagreement
          - If TA-agreed trades outperform by 5–10 pct-points: recommend ALERT
          - Otherwise: HOLD (don't override the analyst's strategy)
        """
        agreed_pnls: list[float] = []
        disagreed_pnls: list[float] = []

        for r in recs:
            pnl = r.get("pnl_pct")
            ta = r.get("ta_agreed")
            if not isinstance(pnl, (int, float)):
                continue
            if ta is True:
                agreed_pnls.append(pnl)
            elif ta is False:
                disagreed_pnls.append(pnl)

        if len(agreed_pnls) < 2 or len(disagreed_pnls) < 2:
            # Not enough data to make a TA call
            return "HOLD"

        avg_agreed = statistics.mean(agreed_pnls)
        avg_disagreed = statistics.mean(disagreed_pnls)
        outperformance = avg_agreed - avg_disagreed  # positive = TA agreement is better

        if outperformance > 0.10:
            return "EXIT"
        if outperformance > 0.05:
            return "ALERT"
        return "HOLD"

    # ─── I/O ────────────────────────────────────────────────────────────────

    def _load_rl_data(self) -> list[dict[str, Any]]:
        """Read all JSONL records from monitor_rl_data.jsonl. Never raises."""
        records: list[dict[str, Any]] = []
        if not self.RL_DATA_FILE.exists():
            logger.warning("RL data file not found: %s", self.RL_DATA_FILE)
            return records

        with self.RL_DATA_FILE.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning("Skipping malformed JSONL line %d: %s", lineno, exc)

        logger.info("Loaded %d RL records from %s", len(records), self.RL_DATA_FILE)
        return records

    def _write_rules(self, rules: MonitorRules) -> None:
        """Atomically write rules to RULES_FILE (temp-file + rename)."""
        self.RULES_FILE.parent.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "analyst_rules": {
                analyst_id: asdict(rule)
                for analyst_id, rule in rules.analyst_rules.items()
            },
        }

        # Atomic write: write to sibling temp file then rename
        tmp_path = self.RULES_FILE.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self.RULES_FILE)
            logger.info("Rules written to %s (%d analysts)", self.RULES_FILE, len(rules.analyst_rules))
        except Exception:
            logger.exception("Failed to write monitor_rules.json")
            tmp_path.unlink(missing_ok=True)
            raise


def load_rules(path: Path = MonitorRulesLearner.RULES_FILE) -> MonitorRules:
    """
    Read monitor_rules.json and return a MonitorRules object.

    Returns an empty MonitorRules (no analyst_rules) if the file is missing or malformed.
    This is the consumption side — called by MonitorAgent to retrieve current rules.
    """
    if not path.exists():
        return MonitorRules()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read monitor_rules.json (%s) — using empty rules", exc)
        return MonitorRules()

    rules = MonitorRules()
    for analyst_id, raw_rule in data.get("analyst_rules", {}).items():
        try:
            rules.analyst_rules[analyst_id] = AnalystRule(**raw_rule)
        except (TypeError, KeyError) as exc:
            logger.warning("Skipping malformed rule for %s: %s", analyst_id, exc)

    return rules


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    learner = MonitorRulesLearner()
    result = learner.learn()
    print(f"Learned rules for {len(result.analyst_rules)} analyst(s):")
    for aid, rule in result.analyst_rules.items():
        print(
            f"  {aid}: min={rule.min_hold_minutes}m max={rule.max_hold_minutes}m "
            f"ta_action={rule.ta_disagreement_action} n={rule.sample_count}"
        )
    sys.exit(0)

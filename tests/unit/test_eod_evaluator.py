"""
tests/unit/test_eod_evaluator.py — Unit tests for EODEvaluator + RL loop.

All tests use an in-memory SQLite DB (:memory:) so they are fast and isolated.
Uses pytest-asyncio with asyncio_mode = "auto" (inherited from pyproject.toml).
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.schemas import Evidence, ExitRules, PositionRecord, TradeSignal
from master.eod_evaluator import (
    EODEvaluator,
    ParameterChange,
    _CONFIDENCE_MAX,
    _CONFIDENCE_MIN,
    _FORBIDDEN_PARAMS,
    _PREMIUM_MAX_USD,
    _PREMIUM_MIN_USD,
)
from master.memory_journal import MemoryJournal


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _make_position(
    analyst_id: str = "vinod_spx",
    symbol: str = "SPX",
    direction: str = "CALL",
    avg_cost_per_share: float = 2.00,
) -> PositionRecord:
    return PositionRecord(
        position_id=str(uuid.uuid4()),
        order_id=str(uuid.uuid4()),
        signal_id=str(uuid.uuid4()),
        analyst_id=analyst_id,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        strike=5000.0,
        expiry=date.today(),
        qty=1,
        avg_cost_per_share=avg_cost_per_share,
        avg_cost_per_contract=avg_cost_per_share * 100,
        opened_at=datetime.now(tz=timezone.utc),
        exit_rules=ExitRules(
            strategy="FIRST_SELL_FROM_SOURCE",
            source_channel_id="123456",
        ),
    )


def _make_signal(
    analyst_id: str = "vinod_spx",
    symbol: str = "SPX",
    direction: str = "CALL",
) -> TradeSignal:
    return TradeSignal(
        analyst_id=analyst_id,
        source_layer="DISCORD",
        timestamp=datetime.now(tz=timezone.utc),
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        strike=5000.0,
        expiry=date.today(),
        signal_price=2.00,
        evidence=[
            Evidence(
                indicator="RSI",
                value=55,
                interpretation="bullish momentum",
                weight=0.7,
                bullish=True,
            )
        ],
        risk_level="MEDIUM",
        confidence=0.75,
        exit_rules=ExitRules(
            strategy="FIRST_SELL_FROM_SOURCE",
            source_channel_id="123456",
        ),
    )


async def _seed_trades(
    journal: MemoryJournal,
    analyst_id: str,
    n_wins: int,
    n_losses: int,
    win_exit_price: float = 3.00,
    loss_exit_price: float = 0.50,
    entry_price: float = 2.00,
) -> None:
    """Insert n_wins WIN trades and n_losses LOSS trades for a given analyst."""
    for _ in range(n_wins):
        pos = _make_position(analyst_id=analyst_id, avg_cost_per_share=entry_price)
        sig = _make_signal(analyst_id=analyst_id)
        await journal.record_close(pos, win_exit_price, "TARGET_HIT", signal=sig)

    for _ in range(n_losses):
        pos = _make_position(analyst_id=analyst_id, avg_cost_per_share=entry_price)
        sig = _make_signal(analyst_id=analyst_id)
        await journal.record_close(pos, loss_exit_price, "STOP_LOSS", signal=sig)


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
async def journal() -> MemoryJournal:
    """Fresh in-memory journal with tables created."""
    jnl = MemoryJournal(db_path=":memory:")
    await jnl.initialize()
    yield jnl
    await jnl.close()


@pytest.fixture
def evaluator(journal: MemoryJournal, tmp_path: Path) -> EODEvaluator:
    """EODEvaluator wired to the in-memory journal and temp dirs."""
    configs_dir = tmp_path / "configs" / "analysts"
    configs_dir.mkdir(parents=True)
    report_path = tmp_path / "shared" / "state" / "rl" / "evaluations.json"

    ev = EODEvaluator(
        journal=journal,
        configs_dir=str(configs_dir),
        report_path=str(report_path),
    )
    return ev


def _write_analyst_config(evaluator: EODEvaluator, analyst_id: str, config: dict) -> None:
    """Helper to pre-populate an analyst config file."""
    path = Path(evaluator.configs_dir) / f"{analyst_id}.json"
    path.write_text(json.dumps(config, indent=2))


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

class TestEvalGeneratesReport:
    """test_eval_generates_report: mock journal with 10 trades -> EvalReport returned."""

    async def test_returns_eval_report_with_date(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """Seeding 10 trades (6 wins, 4 losses) → EvalReport is returned."""
        _write_analyst_config(evaluator, "vinod_spx", {
            "analyst_id": "vinod_spx",
            "confidence_threshold": 0.65,
            "max_premium_usd": 300.0,
        })

        await _seed_trades(journal, "vinod_spx", n_wins=6, n_losses=4)

        report = await evaluator.run_evaluation()

        assert report is not None
        assert report.date == date.today().isoformat()

    async def test_analysts_evaluated_populated(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """Analysts evaluated list contains an entry for vinod_spx."""
        _write_analyst_config(evaluator, "vinod_spx", {
            "analyst_id": "vinod_spx",
            "confidence_threshold": 0.65,
            "max_premium_usd": 300.0,
        })

        await _seed_trades(journal, "vinod_spx", n_wins=6, n_losses=4)

        report = await evaluator.run_evaluation()

        analyst_ids = [s.analyst_id for s in report.analysts_evaluated]
        assert "vinod_spx" in analyst_ids

    async def test_report_total_trades(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """Stats reflect the 10 seeded trades."""
        _write_analyst_config(evaluator, "vinod_spx", {
            "analyst_id": "vinod_spx",
            "confidence_threshold": 0.65,
            "max_premium_usd": 300.0,
        })

        await _seed_trades(journal, "vinod_spx", n_wins=6, n_losses=4)

        report = await evaluator.run_evaluation()

        stats = next(s for s in report.analysts_evaluated if s.analyst_id == "vinod_spx")
        assert stats.total_trades == 10

    async def test_report_written_to_disk(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """Report JSON file is created on disk."""
        _write_analyst_config(evaluator, "vinod_spx", {"analyst_id": "vinod_spx"})
        await _seed_trades(journal, "vinod_spx", n_wins=6, n_losses=4)

        await evaluator.run_evaluation()

        assert Path(evaluator.report_path).exists()
        with open(evaluator.report_path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["date"] == date.today().isoformat()


class TestParameterChangeApplied:
    """test_parameter_change_applied: low win-rate analyst -> confidence_threshold raised."""

    async def test_low_win_rate_raises_confidence(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """Analyst with 2 wins / 8 losses (20% win rate) gets confidence_threshold raised."""
        _write_analyst_config(evaluator, "adi", {
            "analyst_id": "adi",
            "confidence_threshold": 0.65,
            "max_premium_usd": 300.0,
        })

        # 2 wins, 8 losses → 20% win rate (well below 40% threshold)
        await _seed_trades(journal, "adi", n_wins=2, n_losses=8)

        report = await evaluator.run_evaluation()

        confidence_changes = [
            c for c in report.changes_made
            if c.analyst_id == "adi" and c.parameter == "confidence_threshold"
        ]
        assert len(confidence_changes) == 1
        change = confidence_changes[0]
        assert change.new_value > change.old_value, "confidence_threshold should increase"
        assert change.new_value == pytest.approx(0.70, abs=1e-6)

    async def test_config_file_updated_on_disk(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """The analyst config JSON file is updated after a change is applied."""
        _write_analyst_config(evaluator, "adi", {
            "analyst_id": "adi",
            "confidence_threshold": 0.65,
            "max_premium_usd": 300.0,
        })

        await _seed_trades(journal, "adi", n_wins=2, n_losses=8)
        await evaluator.run_evaluation()

        config_path = Path(evaluator.configs_dir) / "adi.json"
        with config_path.open() as f:
            updated = json.load(f)

        assert updated["confidence_threshold"] == pytest.approx(0.70, abs=1e-6)

    async def test_high_win_rate_lowers_confidence(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """Analyst with 8 wins / 2 losses (80% win rate) + positive avg_pnl
        gets confidence_threshold lowered to capture more signals."""
        _write_analyst_config(evaluator, "albert", {
            "analyst_id": "albert",
            "confidence_threshold": 0.75,
            "max_premium_usd": 300.0,
        })

        # 8 wins with large gain, 2 losses with small loss → high win rate + positive pnl
        await _seed_trades(
            journal,
            "albert",
            n_wins=8,
            n_losses=2,
            win_exit_price=4.00,   # +100% pnl
            loss_exit_price=1.80,  # -10% pnl
            entry_price=2.00,
        )

        report = await evaluator.run_evaluation()

        confidence_changes = [
            c for c in report.changes_made
            if c.analyst_id == "albert" and c.parameter == "confidence_threshold"
        ]
        assert len(confidence_changes) == 1
        assert confidence_changes[0].new_value < confidence_changes[0].old_value


class TestMaxChangesRespected:
    """test_max_changes_respected: 5 analysts all need changes -> only 3 applied."""

    async def test_only_three_changes_applied(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """When 5 analysts each need a confidence_threshold change, only 3 are applied."""
        analyst_ids = ["vinod_spx", "adi", "albert", "everest", "mag7"]

        for aid in analyst_ids:
            _write_analyst_config(evaluator, aid, {
                "analyst_id": aid,
                "confidence_threshold": 0.65,
                "max_premium_usd": 300.0,
            })
            # 1 win, 9 losses → 10% win rate → triggers confidence raise + premium cut
            await _seed_trades(journal, aid, n_wins=1, n_losses=9)

        report = await evaluator.run_evaluation()

        total_applied = len(report.changes_made)
        assert total_applied <= EODEvaluator.MAX_CHANGES_PER_EVAL, (
            f"Expected at most {EODEvaluator.MAX_CHANGES_PER_EVAL} changes, "
            f"got {total_applied}"
        )

    async def test_excess_changes_go_to_deferred(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """Changes beyond the cap end up in changes_deferred, not silently dropped."""
        analyst_ids = ["vinod_spx", "adi", "albert", "everest", "mag7"]

        for aid in analyst_ids:
            _write_analyst_config(evaluator, aid, {
                "analyst_id": aid,
                "confidence_threshold": 0.65,
                "max_premium_usd": 300.0,
            })
            await _seed_trades(journal, aid, n_wins=1, n_losses=9)

        report = await evaluator.run_evaluation()

        total = len(report.changes_made) + len(report.changes_deferred)
        assert total > EODEvaluator.MAX_CHANGES_PER_EVAL, (
            "Expected more candidates than the cap so deferred list is non-empty"
        )
        assert len(report.changes_deferred) > 0


class TestHardLimitsEnforced:
    """test_hard_limits_enforced: threshold can't go below 0.50 or above 0.90."""

    async def test_confidence_threshold_floor(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """confidence_threshold cannot drop below 0.50 even with repeated good performance."""
        # Start at minimum already
        _write_analyst_config(evaluator, "vinod_spx", {
            "analyst_id": "vinod_spx",
            "confidence_threshold": _CONFIDENCE_MIN,
            "max_premium_usd": 300.0,
        })

        # 9 wins / 1 loss → strong performance → would try to lower confidence
        await _seed_trades(
            journal,
            "vinod_spx",
            n_wins=9,
            n_losses=1,
            win_exit_price=5.00,
            entry_price=2.00,
        )

        report = await evaluator.run_evaluation()

        for change in report.changes_made:
            if change.parameter == "confidence_threshold":
                assert change.new_value >= _CONFIDENCE_MIN, (
                    f"confidence_threshold {change.new_value} is below floor {_CONFIDENCE_MIN}"
                )

    async def test_confidence_threshold_ceiling(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """confidence_threshold cannot exceed 0.90 even with very poor performance."""
        _write_analyst_config(evaluator, "adi", {
            "analyst_id": "adi",
            "confidence_threshold": _CONFIDENCE_MAX,
            "max_premium_usd": 300.0,
        })

        # 0 wins / 10 losses → terrible → would try to raise confidence above max
        await _seed_trades(journal, "adi", n_wins=0, n_losses=10)

        report = await evaluator.run_evaluation()

        for change in report.changes_made:
            if change.parameter == "confidence_threshold":
                assert change.new_value <= _CONFIDENCE_MAX, (
                    f"confidence_threshold {change.new_value} exceeds ceiling {_CONFIDENCE_MAX}"
                )

    async def test_max_premium_floor(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """max_premium_usd cannot drop below $100."""
        _write_analyst_config(evaluator, "everest", {
            "analyst_id": "everest",
            "confidence_threshold": 0.65,
            "max_premium_usd": _PREMIUM_MIN_USD,
        })

        # 0 wins / 10 losses → avg_pnl < -10% → would try to cut premium further
        await _seed_trades(
            journal,
            "everest",
            n_wins=0,
            n_losses=10,
            loss_exit_price=0.50,
            entry_price=2.00,
        )

        report = await evaluator.run_evaluation()

        for change in report.changes_made:
            if change.analyst_id == "everest" and change.parameter == "max_premium_usd":
                assert change.new_value >= _PREMIUM_MIN_USD

    async def test_max_premium_ceiling(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """max_premium_usd cannot exceed $500."""
        _write_analyst_config(evaluator, "mag7", {
            "analyst_id": "mag7",
            "confidence_threshold": 0.65,
            "max_premium_usd": _PREMIUM_MAX_USD,
        })

        # 9 wins / 1 loss + excellent pnl → would try to raise premium above max
        await _seed_trades(
            journal,
            "mag7",
            n_wins=9,
            n_losses=1,
            win_exit_price=6.00,
            entry_price=2.00,
        )

        report = await evaluator.run_evaluation()

        for change in report.changes_made:
            if change.analyst_id == "mag7" and change.parameter == "max_premium_usd":
                assert change.new_value <= _PREMIUM_MAX_USD


class TestNoPositionSizingChanges:
    """test_no_position_sizing_changes: no changes to forbidden params (never auto-change)."""

    async def test_forbidden_params_never_in_changes(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """
        Even with terrible performance, forbidden params like max_position_size_usd,
        paper_mode, kill_switch are never touched.
        """
        config = {
            "analyst_id": "vinod_spx",
            "confidence_threshold": 0.65,
            "max_premium_usd": 300.0,
            # Include forbidden params in config to ensure they are never modified
            "max_position_size_usd": 200.0,
            "paper_mode": True,
            "kill_switch": False,
        }
        _write_analyst_config(evaluator, "vinod_spx", config)

        # Terrible performance
        await _seed_trades(journal, "vinod_spx", n_wins=0, n_losses=10)

        report = await evaluator.run_evaluation()

        all_changes = report.changes_made + report.changes_deferred
        changed_params = {c.parameter for c in all_changes}

        for forbidden in _FORBIDDEN_PARAMS:
            assert forbidden not in changed_params, (
                f"Forbidden parameter '{forbidden}' was changed by RL — this must never happen"
            )

    async def test_forbidden_params_not_in_generated_candidates(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """_generate_parameter_changes never returns a ParameterChange for a forbidden param."""
        from master.eod_evaluator import AnalystStats

        stats = [
            AnalystStats(
                analyst_id="vinod_spx",
                total_trades=10,
                win_rate=0.20,
                avg_pnl_pct=-0.30,
                worst_pattern="SPX_CALL",
                best_pattern="SPX_CALL",
            )
        ]

        _write_analyst_config(evaluator, "vinod_spx", {
            "analyst_id": "vinod_spx",
            "confidence_threshold": 0.65,
            "max_premium_usd": 300.0,
            "max_position_size_usd": 200.0,
        })

        changes = await evaluator._generate_parameter_changes(stats)

        for change in changes:
            assert change.parameter not in _FORBIDDEN_PARAMS, (
                f"_generate_parameter_changes proposed change to forbidden param: "
                f"{change.parameter}"
            )

    async def test_apply_changes_blocks_forbidden_param(
        self, journal: MemoryJournal, evaluator: EODEvaluator
    ) -> None:
        """_apply_changes silently rejects any change to a forbidden parameter."""
        _write_analyst_config(evaluator, "vinod_spx", {
            "analyst_id": "vinod_spx",
            "max_position_size_usd": 200.0,
            "paper_mode": True,
        })

        bad_change = ParameterChange(
            analyst_id="vinod_spx",
            parameter="max_position_size_usd",
            old_value=200.0,
            new_value=400.0,
            reason="attempt to auto-change position size",
        )

        # Should not raise, but should not modify the config file either
        await evaluator._apply_changes([bad_change])

        config = evaluator._load_analyst_config("vinod_spx")
        assert config["max_position_size_usd"] == pytest.approx(200.0), (
            "Forbidden param max_position_size_usd was modified despite the guard"
        )

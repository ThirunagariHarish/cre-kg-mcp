"""Unit tests for core/kelly_sizer.py."""

from __future__ import annotations

import pytest

from core.kelly_sizer import (
    DEFAULT_POSITION_USD,
    MAX_KELLY_FRACTION,
    MIN_POSITION_USD,
    MIN_TRADES_REQUIRED,
    KellyResult,
    compute_kelly_size,
)


class TestKellySizer:
    # ------------------------------------------------------------------
    # Positive edge — should get a meaningful position > $50
    # ------------------------------------------------------------------

    def test_positive_edge(self):
        """win_rate=0.6, avg_win=0.08, avg_loss=0.04 on $10k → positive size."""
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.6,
            avg_win_pct=0.08,
            avg_loss_pct=0.04,
            trades_count=50,
        )
        assert isinstance(result, KellyResult)
        assert result.position_size_usd > 0
        assert result.kelly_fraction > 0

    def test_positive_edge_spec_values(self):
        """Spec example: win_rate=0.6, avg_win=0.8, avg_loss=0.4, bankroll=10000."""
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.6,
            avg_win_pct=0.8,
            avg_loss_pct=0.4,
            trades_count=50,
        )
        assert result.position_size_usd > 0
        # b = 0.8/0.4 = 2, kelly = (0.6*2 - 0.4)/2 = 0.8/2 = 0.40 -> capped at 0.25
        assert result.capped is True
        assert result.kelly_fraction == pytest.approx(MAX_KELLY_FRACTION)

    # ------------------------------------------------------------------
    # Negative edge — Kelly goes negative → minimum $50
    # ------------------------------------------------------------------

    def test_negative_edge(self):
        """win_rate=0.3, avg_win=0.02, avg_loss=0.05 → negative Kelly → $50 floor."""
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.3,
            avg_win_pct=0.02,
            avg_loss_pct=0.05,
            trades_count=50,
        )
        assert result.position_size_usd == pytest.approx(MIN_POSITION_USD)
        assert result.kelly_fraction == 0.0

    def test_negative_edge_spec_values(self):
        """Spec values: win_rate=0.3, avg_win=0.2, avg_loss=0.5."""
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.3,
            avg_win_pct=0.2,
            avg_loss_pct=0.5,
            trades_count=50,
        )
        # b = 0.2/0.5 = 0.4, kelly = (0.3*0.4 - 0.7)/0.4 = (0.12-0.7)/0.4 = -1.45 → negative
        assert result.position_size_usd == pytest.approx(MIN_POSITION_USD)
        assert result.kelly_fraction == 0.0

    # ------------------------------------------------------------------
    # Capping at 25%
    # ------------------------------------------------------------------

    def test_capped_at_25pct(self):
        """Very high edge → capped=True and kelly_fraction == MAX_KELLY_FRACTION."""
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.9,
            avg_win_pct=0.5,
            avg_loss_pct=0.1,
            trades_count=100,
        )
        assert result.capped is True
        assert result.kelly_fraction == pytest.approx(MAX_KELLY_FRACTION)
        # position = 10000 * 0.25 = 2500 but capped by max_position_usd=200
        assert result.position_size_usd == pytest.approx(DEFAULT_POSITION_USD)

    def test_capped_respects_max_position_usd(self):
        """Even if kelly fraction * bankroll > max_position_usd, we cap at max."""
        result = compute_kelly_size(
            bankroll_usd=100_000,
            win_rate=0.8,
            avg_win_pct=0.3,
            avg_loss_pct=0.1,
            trades_count=100,
            max_position_usd=500,
        )
        assert result.position_size_usd <= 500

    # ------------------------------------------------------------------
    # Insufficient data → default $200
    # ------------------------------------------------------------------

    def test_insufficient_data_default(self):
        """15 trades (< MIN_TRADES_REQUIRED=20) → default $200."""
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.6,
            avg_win_pct=0.08,
            avg_loss_pct=0.04,
            trades_count=15,
        )
        assert result.position_size_usd == pytest.approx(DEFAULT_POSITION_USD)
        assert result.kelly_fraction == 0.0
        assert str(MIN_TRADES_REQUIRED) in result.reason

    def test_zero_trades_default(self):
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.6,
            avg_win_pct=0.08,
            avg_loss_pct=0.04,
            trades_count=0,
        )
        assert result.position_size_usd == pytest.approx(DEFAULT_POSITION_USD)

    # ------------------------------------------------------------------
    # Minimum $50 floor
    # ------------------------------------------------------------------

    def test_min_50_floor_small_bankroll(self):
        """Very small bankroll → kelly * bankroll < $50 → floor at $50."""
        result = compute_kelly_size(
            bankroll_usd=100,
            win_rate=0.55,
            avg_win_pct=0.02,
            avg_loss_pct=0.02,
            trades_count=30,
        )
        assert result.position_size_usd >= MIN_POSITION_USD

    def test_min_50_floor(self):
        """Tiny kelly fraction on small bankroll → always at least $50."""
        result = compute_kelly_size(
            bankroll_usd=200,
            win_rate=0.51,
            avg_win_pct=0.01,
            avg_loss_pct=0.009,
            trades_count=25,
        )
        assert result.position_size_usd >= MIN_POSITION_USD

    # ------------------------------------------------------------------
    # Invalid input guards
    # ------------------------------------------------------------------

    def test_zero_avg_win_pct_returns_default(self):
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.6,
            avg_win_pct=0.0,
            avg_loss_pct=0.04,
            trades_count=50,
        )
        assert result.position_size_usd == pytest.approx(DEFAULT_POSITION_USD)

    def test_zero_avg_loss_pct_returns_default(self):
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.6,
            avg_win_pct=0.08,
            avg_loss_pct=0.0,
            trades_count=50,
        )
        assert result.position_size_usd == pytest.approx(DEFAULT_POSITION_USD)

    # ------------------------------------------------------------------
    # KellyResult fields are populated
    # ------------------------------------------------------------------

    def test_result_fields_populated(self):
        result = compute_kelly_size(
            bankroll_usd=10_000,
            win_rate=0.6,
            avg_win_pct=0.08,
            avg_loss_pct=0.04,
            trades_count=50,
        )
        assert result.win_rate == pytest.approx(0.6)
        assert result.avg_win_pct == pytest.approx(0.08)
        assert result.avg_loss_pct == pytest.approx(0.04)
        assert result.trades_used == 50
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0

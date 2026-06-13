"""Kelly Criterion position sizer for AnalystTeam trade recommendations."""

from __future__ import annotations

from dataclasses import dataclass

MAX_KELLY_FRACTION = 0.25  # cap at 25% of bankroll
MIN_TRADES_REQUIRED = 20   # need at least 20 historical trades
DEFAULT_POSITION_USD = 200.0
MIN_POSITION_USD = 50.0    # hard floor


@dataclass
class KellyResult:
    position_size_usd: float
    kelly_fraction: float
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    trades_used: int
    capped: bool
    reason: str


def compute_kelly_size(
    bankroll_usd: float,
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    trades_count: int,
    max_position_usd: float = DEFAULT_POSITION_USD,
) -> KellyResult:
    """Compute Kelly-optimal position size.

    Args:
        bankroll_usd:    Total account value in USD.
        win_rate:        Fraction of trades that are winners (0 < x < 1).
        avg_win_pct:     Average gain on winning trades as a positive decimal (e.g. 0.08 = 8%).
        avg_loss_pct:    Average loss on losing trades as a positive decimal (e.g. 0.04 = 4%).
        trades_count:    Number of historical trades used to calculate the stats.
        max_position_usd: Hard cap on position size (default DEFAULT_POSITION_USD).

    Returns:
        KellyResult with all sizing details.
    """
    _defaults = dict(
        win_rate=win_rate,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        trades_used=trades_count,
        capped=False,
    )

    # Guard: insufficient history
    if trades_count < MIN_TRADES_REQUIRED:
        return KellyResult(
            position_size_usd=round(min(DEFAULT_POSITION_USD, max_position_usd), 2),
            kelly_fraction=0.0,
            reason=f"insufficient data ({trades_count}/{MIN_TRADES_REQUIRED} trades required)",
            **_defaults,
        )

    # Guard: invalid percentages
    if avg_win_pct <= 0 or avg_loss_pct <= 0:
        return KellyResult(
            position_size_usd=round(min(DEFAULT_POSITION_USD, max_position_usd), 2),
            kelly_fraction=0.0,
            reason="invalid win/loss percentages (must be > 0)",
            **_defaults,
        )

    # Kelly formula: f* = (b * p - q) / b  where b = avg_win / avg_loss
    b = avg_win_pct / avg_loss_pct
    loss_rate = 1.0 - win_rate
    kelly_f = (win_rate * b - loss_rate) / b

    # Negative Kelly means negative edge — use minimum position
    if kelly_f <= 0.0:
        return KellyResult(
            position_size_usd=MIN_POSITION_USD,
            kelly_fraction=0.0,
            reason="negative Kelly edge — using minimum position",
            **_defaults,
        )

    capped = kelly_f > MAX_KELLY_FRACTION
    kelly_f = min(kelly_f, MAX_KELLY_FRACTION)

    raw_size = bankroll_usd * kelly_f
    size = min(raw_size, max_position_usd)
    size = max(size, MIN_POSITION_USD)

    reason = "kelly capped at 25%" if capped else "kelly sizing applied"

    return KellyResult(
        position_size_usd=round(size, 2),
        kelly_fraction=kelly_f,
        win_rate=win_rate,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        trades_used=trades_count,
        capped=capped,
        reason=reason,
    )

"""Earnings Momentum Agent — gap-and-go plays on earnings beats/misses."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from .base import AgentStrategyBase

logger = logging.getLogger(__name__)


class UWEarningsAgent(AgentStrategyBase):
    """
    Monitors UW earnings data for high-expected-move tickers.
    Generates straddle signals before earnings for high IV plays.
    """

    AGENT_ID = "uw_earnings_agent"
    DISPLAY_NAME = "UW Earnings Agent"
    CATEGORY = "ALGORITHM"
    SCAN_INTERVAL_SEC = 1800  # 30 min

    def __init__(self, uw_adapter: Any) -> None:
        super().__init__()
        self._uw = uw_adapter
        self._seen: set[str] = set()

    async def scan(self) -> list[dict[str, Any]]:
        result = await self._uw.earnings_premarket()
        earnings = result.get("data", [])
        signals = []

        for e in earnings:
            ticker = e.get("ticker") or e.get("symbol") or ""
            if not ticker or ticker in self._seen:
                continue

            expected_move_pct = float(e.get("expected_move_perc") or e.get("expected_move") or 0)
            if expected_move_pct < 5.0:  # Only trade if expected move > 5%
                continue

            self._seen.add(ticker)
            # Get expiry = nearest Friday after today
            today = date.today()
            days_until_friday = (4 - today.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            expiry = (today + timedelta(days=days_until_friday)).strftime("%Y-%m-%d")

            # Buy ATM straddle (call + put) — need current price for strike
            # Use the long straddle metrics if available
            straddle_cost = float(e.get("long_straddle") or 0)
            last_price = float(e.get("last_price") or 0)

            if last_price > 0:
                strike = round(last_price / 5) * 5

                signals.append({
                    "ticker": ticker.upper(),
                    "side": "long",
                    "option_type": "call",  # Buy call leg
                    "strike": float(strike),
                    "expiry": expiry,
                    "quantity": 1,
                    "confidence": 0.68,
                    "stop_loss_pct": 40.0,
                    "take_profit_pct": 60.0,
                    "rationale": (
                        f"Earnings play: expected_move={expected_move_pct:.1f}% "
                        f"straddle_cost=${straddle_cost:.2f} last=${last_price:.2f}"
                    ),
                })

        return signals[:2]  # max 2 earnings plays per scan


__all__ = ["UWEarningsAgent"]

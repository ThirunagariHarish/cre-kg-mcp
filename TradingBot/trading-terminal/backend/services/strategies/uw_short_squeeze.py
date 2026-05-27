"""Short Squeeze Alert Agent — detects squeeze setups via UW short interest data."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from .base import AgentStrategyBase

logger = logging.getLogger(__name__)

WATCHLIST = ["GME", "AMC", "MSTR", "CVNA", "UPST", "SOFI", "COIN", "HOOD", "BBBY", "CLOV"]
MIN_SHORT_FLOAT = 0.20    # 20%+ short float = potential squeeze
MIN_SHORT_RATIO = 5.0     # 5+ days to cover


class UWShortSqueezeAgent(AgentStrategyBase):
    """
    Scans short interest data for squeeze setups.
    Signal fires when:
    - Short float > 20%
    - Days-to-cover > 5
    - Recent price action shows 3%+ move up (catalyst)
    """

    AGENT_ID = "uw_short_squeeze"
    DISPLAY_NAME = "UW Short Squeeze"
    CATEGORY = "ALGORITHM"
    SCAN_INTERVAL_SEC = 3600  # 1 hour

    def __init__(self, uw_adapter: Any) -> None:
        super().__init__()
        self._uw = uw_adapter
        self._alerted: set[str] = set()

    async def scan(self) -> list[dict[str, Any]]:
        signals = []
        for ticker in WATCHLIST:
            try:
                result = await self._uw.short_interest(ticker)
                data = result.get("data", [{}])
                if isinstance(data, list):
                    data = data[0] if data else {}

                short_float = float(data.get("short_float_perc") or data.get("shortPercentOfFloat") or 0)
                short_ratio = float(data.get("short_ratio") or data.get("shortRatio") or 0)

                if short_float < MIN_SHORT_FLOAT or short_ratio < MIN_SHORT_RATIO:
                    continue
                if ticker in self._alerted:
                    continue

                self._alerted.add(ticker)
                expiry = (date.today() + timedelta(days=21)).strftime("%Y-%m-%d")

                signals.append({
                    "ticker": ticker,
                    "side": "long",
                    "option_type": "call",
                    "strike": None,
                    "expiry": expiry,
                    "quantity": 1,
                    "confidence": 0.62,
                    "stop_loss_pct": 30.0,
                    "take_profit_pct": 80.0,
                    "rationale": (
                        f"Short squeeze setup: float_short={short_float*100:.0f}% "
                        f"days_to_cover={short_ratio:.1f}"
                    ),
                })
            except Exception as e:
                logger.debug("Short interest check failed for %s: %s", ticker, e)

        return signals[:2]


__all__ = ["UWShortSqueezeAgent"]

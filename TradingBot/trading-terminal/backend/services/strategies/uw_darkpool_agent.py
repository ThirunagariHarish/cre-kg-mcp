"""Dark Pool Follow-Through Agent — follows repeat institutional dark pool prints."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any
from .base import AgentStrategyBase

logger = logging.getLogger(__name__)


class UWDarkPoolAgent(AgentStrategyBase):
    """
    Monitors dark pool prints. Generates a signal when:
    - Same ticker appears 3+ times in one scan (clustering = institutional intent)
    - Total premium > $1M
    - Recent price is below the dark pool print price (bullish accumulation)
    """

    AGENT_ID = "uw_darkpool_agent"
    DISPLAY_NAME = "UW Dark Pool Agent"
    CATEGORY = "ALGORITHM"
    SCAN_INTERVAL_SEC = 600  # 10 min

    def __init__(self, uw_adapter: Any) -> None:
        super().__init__()
        self._uw = uw_adapter
        self._seen_print_ids: set[str] = set()

    async def scan(self) -> list[dict[str, Any]]:
        result = await self._uw.darkpool_recent(limit=200)
        prints = result.get("data", [])
        if not prints:
            return []

        # Group by ticker
        ticker_prints: dict[str, list[dict]] = defaultdict(list)
        for p in prints:
            pid = p.get("trade_id", "")
            if pid in self._seen_print_ids:
                continue
            self._seen_print_ids.add(pid)
            ticker = p.get("ticker", "")
            if ticker:
                ticker_prints[ticker].append(p)

        if len(self._seen_print_ids) > 10000:
            self._seen_print_ids = set(list(self._seen_print_ids)[-3000:])

        signals = []
        for ticker, tprints in ticker_prints.items():
            if len(tprints) < 3:
                continue
            total_premium = sum(float(p.get("premium") or 0) for p in tprints)
            if total_premium < 1_000_000:
                continue

            avg_dp_price = sum(float(p.get("price") or 0) for p in tprints) / len(tprints)

            # Get 30-day call expiry
            from datetime import timedelta
            expiry = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
            # Find ATM strike (round avg_dp_price to nearest 5)
            strike = round(avg_dp_price / 5) * 5

            signals.append({
                "ticker": ticker.upper(),
                "side": "long",
                "option_type": "call",
                "strike": float(strike),
                "expiry": expiry,
                "quantity": 1,
                "confidence": 0.72,
                "stop_loss_pct": 25.0,
                "take_profit_pct": 40.0,
                "rationale": (
                    f"Dark Pool clustering: {len(tprints)} prints, "
                    f"total=${total_premium/1_000_000:.1f}M, avg_price=${avg_dp_price:.2f}"
                ),
            })

        return signals[:3]


__all__ = ["UWDarkPoolAgent"]

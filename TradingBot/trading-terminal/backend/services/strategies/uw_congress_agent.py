"""Congressional Trade Follow-Through Agent."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from .base import AgentStrategyBase

logger = logging.getLogger(__name__)


class UWCongressAgent(AgentStrategyBase):
    """
    Monitors congressional stock trades.
    Follows purchases by representatives/senators within 2 trading days of disclosure.
    Congress members must disclose within 45 days — any disclosure for a recent trade is actionable.
    """

    AGENT_ID = "uw_congress_agent"
    DISPLAY_NAME = "UW Congress Agent"
    CATEGORY = "ALGORITHM"
    SCAN_INTERVAL_SEC = 3600  # 1 hour

    def __init__(self, uw_adapter: Any) -> None:
        super().__init__()
        self._uw = uw_adapter
        self._seen: set[str] = set()

    async def scan(self) -> list[dict[str, Any]]:
        result = await self._uw.congress_trades(limit=50)
        trades = result.get("data", [])
        signals = []

        for t in trades:
            key = f"{t.get('ticker')}_{t.get('date')}_{t.get('congress_member')}"
            if key in self._seen:
                continue
            self._seen.add(key)

            ticker = t.get("ticker") or ""
            trade_type = (t.get("trade_type") or "").upper()
            asset_type = (t.get("asset_type") or "").upper()
            amount_str = t.get("amount") or ""

            if not ticker or trade_type != "BUY":
                continue
            if "OPTION" in asset_type:
                continue  # Skip options (complex to follow)
            if "STOCK" not in asset_type and "COMMON" not in asset_type and asset_type not in ("STOCK", ""):
                continue

            # Only follow significant purchases
            # Amount comes as range like "$50,001 - $100,000"
            try:
                min_amount = int(amount_str.replace("$", "").replace(",", "").split("-")[0].strip())
                if min_amount < 15_000:
                    continue
            except Exception:
                continue

            # Buy 30-day call
            expiry = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")

            signals.append({
                "ticker": ticker.upper(),
                "side": "long",
                "option_type": "call",
                "strike": None,  # Let execution find ATM
                "expiry": expiry,
                "quantity": 1,
                "confidence": 0.65,
                "stop_loss_pct": 20.0,
                "take_profit_pct": 35.0,
                "rationale": (
                    f"Congress follow-through: {t.get('congress_member')} bought "
                    f"{ticker} {amount_str} ({t.get('house')}, {t.get('party')})"
                ),
            })

        return signals[:2]


__all__ = ["UWCongressAgent"]

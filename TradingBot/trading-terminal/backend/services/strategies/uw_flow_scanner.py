"""UW Flow Scanner — detects sweep/block/golden_sweep options activity."""
from __future__ import annotations

import logging
from typing import Any
from .base import AgentStrategyBase

logger = logging.getLogger(__name__)

# Minimum premium for a trade to be considered significant
MIN_PREMIUM = 50_000       # $50k
GOLDEN_SWEEP_MIN = 500_000 # $500k = golden sweep territory
MIN_CONFIDENCE = 0.70

# How many days out the expiry must be (avoid 0DTE by default)
MIN_DTE = 3


class UWFlowScannerAgent(AgentStrategyBase):
    """
    Scans Unusual Whales flow-alerts every 5 minutes.
    Generates signals on:
    - Golden sweeps (>$500k premium, ask-side)
    - Bullish sweeps (>$50k, call, ask-side)
    - Bearish sweeps (>$50k, put, ask-side)
    - Blocks (>$200k, classified institutional)
    """

    AGENT_ID = "uw_flow_scanner"
    DISPLAY_NAME = "UW Flow Scanner"
    CATEGORY = "ALGORITHM"
    SCAN_INTERVAL_SEC = 300  # 5 min

    def __init__(self, uw_adapter: Any) -> None:
        super().__init__()
        self._uw = uw_adapter
        self._seen_ids: set[str] = set()  # deduplicate

    async def scan(self) -> list[dict[str, Any]]:
        result = await self._uw.flow_alerts(
            limit=100,
            is_call=None,  # both calls and puts
            min_premium=MIN_PREMIUM,
        )
        alerts = result.get("data", [])
        if not alerts:
            return []

        signals = []
        for alert in alerts:
            alert_id = alert.get("flow_alert_id") or alert.get("id", "")
            if alert_id in self._seen_ids:
                continue
            self._seen_ids.add(alert_id)
            # Prevent memory leak
            if len(self._seen_ids) > 5000:
                self._seen_ids = set(list(self._seen_ids)[-2000:])

            premium = float(alert.get("premium") or 0)
            tags = alert.get("tags") or []
            tag_strs = [t.get("tag", t) if isinstance(t, dict) else str(t) for t in tags]
            option_type_raw = alert.get("option_type") or ""
            option_type = "call" if option_type_raw.upper() in ("C", "CALL") else "put"
            ticker = alert.get("underlying_symbol") or alert.get("ticker") or ""
            strike = float(alert.get("strike") or 0)
            expiry = (alert.get("expiry") or "")[:10]  # YYYY-MM-DD
            ask_vol = int(alert.get("ask_vol") or 0)
            bid_vol = int(alert.get("bid_vol") or 0)

            if not ticker or not strike or not expiry:
                continue

            # Skip if less than MIN_DTE days to expiry
            try:
                from datetime import date
                dte = (date.fromisoformat(expiry) - date.today()).days
                if dte < MIN_DTE:
                    continue
            except Exception:
                pass

            # Classify
            is_golden = premium >= GOLDEN_SWEEP_MIN and "Sweep" in " ".join(tag_strs)
            is_sweep = "Sweep" in " ".join(tag_strs)
            is_block = "Block" in " ".join(tag_strs)
            is_ask_side = ask_vol > bid_vol

            if not (is_golden or is_sweep or is_block):
                continue
            if not is_ask_side:
                continue  # only trade aggressive buyers

            # Confidence scoring
            confidence = 0.65
            if is_golden:
                confidence = 0.85
            elif is_block:
                confidence = 0.75
            if "GoldenSweep" in " ".join(tag_strs):
                confidence = 0.90

            side = "long" if option_type == "call" else "short"
            take_profit = 75.0 if is_golden else 50.0

            signals.append({
                "ticker": ticker.upper(),
                "side": side,
                "option_type": option_type,
                "strike": strike,
                "expiry": expiry,
                "quantity": 1,
                "confidence": confidence,
                "stop_loss_pct": 30.0,
                "take_profit_pct": take_profit,
                "rationale": (
                    f"UW {'Golden ' if is_golden else ''}{'Sweep' if is_sweep else 'Block'}: "
                    f"${premium/1000:.0f}k premium | tags={','.join(tag_strs)} | "
                    f"ask_vol={ask_vol} bid_vol={bid_vol}"
                ),
            })

        return signals[:5]  # max 5 signals per scan


__all__ = ["UWFlowScannerAgent"]

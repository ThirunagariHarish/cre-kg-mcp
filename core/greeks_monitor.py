"""
core/greeks_monitor.py — Live Greeks & P&L monitor for open option positions.

Fetches real-time option quotes via Polygon (or yfinance fallback), computes
P&L and risk metrics, and writes a summary to shared/state/position_greeks.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GREEKS_FILE = Path("shared/state/position_greeks.json")


@dataclass
class PositionGreeks:
    """Greeks + P&L snapshot for a single open position."""

    position_id: str
    symbol: str
    direction: str
    strike: float
    expiry: str           # ISO date string for JSON serialisability
    current_price: float  # mark per share
    entry_price: float    # avg_cost_per_share
    pnl_per_share: float
    pnl_pct: float
    pnl_per_contract: float  # pnl_per_share * 100
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    implied_volatility: float | None
    days_to_expiry: int
    theta_decay_pct: float | None  # abs(theta) as fraction of position value/day
    bid: float
    ask: float
    spread_pct: float     # (ask - bid) / mid
    volume: int
    open_interest: int
    updated_at: str       # ISO datetime string
    account_id: str = "primary"
    alert: str | None = None  # "HIGH_THETA_DECAY" | "WIDE_SPREAD" | "LOW_OI" | "NEAR_EXPIRY"


class GreeksMonitor:
    """Refreshes Greeks for all open positions and writes results to disk."""

    THETA_DECAY_ALERT_PCT = 0.03   # alert if daily theta > 3% of position value
    SPREAD_ALERT_PCT = 0.15        # alert if bid/ask spread > 15% of mid
    LOW_OI_THRESHOLD = 100

    def __init__(self, polygon_client: Any = None) -> None:
        self._polygon = polygon_client
        self._log = logging.getLogger("greeks_monitor")

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    async def refresh_all(self, positions: list[Any]) -> list[PositionGreeks]:
        """Refresh all positions concurrently and write results to GREEKS_FILE."""
        tasks = [self._refresh_position(pos) for pos in positions]
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)

        greeks: list[PositionGreeks] = []
        for i, result in enumerate(results_raw):
            if isinstance(result, Exception):
                self._log.warning(
                    "Failed to refresh position %s: %s",
                    getattr(positions[i], "position_id", i),
                    result,
                )
            else:
                greeks.append(result)

        await asyncio.to_thread(self._write_greeks_file, greeks)
        return greeks

    # ─────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────

    async def _refresh_position(self, pos: Any) -> PositionGreeks:
        """Fetch live quote and compute all metrics for one position."""
        from core.polygon_client import get_polygon_client  # noqa: PLC0415 — lazy to avoid circular

        client = self._polygon or get_polygon_client()
        contract = await client.get_option_quote(
            pos.symbol,
            pos.direction,
            pos.strike,
            pos.expiry,
        )

        now = datetime.now(timezone.utc)
        expiry_date = pos.expiry if hasattr(pos.expiry, "year") else pos.expiry
        dte = max(0, (expiry_date - now.date()).days)

        # ── Prices & P&L ──────────────────────────────────────────────────────
        if contract is not None:
            current_price = contract.mark_per_share
            bid = contract.bid_per_share
            ask = contract.ask_per_share
            mid = (ask + bid) / 2
            spread_pct = (ask - bid) / mid if mid > 0 else 0.0
            volume = contract.volume
            open_interest = contract.open_interest
            delta = contract.delta
            implied_volatility = contract.implied_volatility
            # Polygon v3 snapshot doesn't expose gamma/theta/vega directly in our
            # current parser — they'd come from the greeks sub-object if present.
            gamma: float | None = None
            theta: float | None = None
            vega: float | None = None
        else:
            # Fallback: use entry price as best estimate
            current_price = pos.avg_cost_per_share
            bid = pos.avg_cost_per_share
            ask = pos.avg_cost_per_share
            spread_pct = 0.0
            volume = 0
            open_interest = 0
            delta = None
            gamma = None
            theta = None
            vega = None
            implied_volatility = None

        entry_price = pos.avg_cost_per_share
        pnl_per_share = current_price - entry_price
        pnl_pct = pnl_per_share / entry_price if entry_price != 0 else 0.0
        pnl_per_contract = pnl_per_share * 100

        # ── Theta decay % ──────────────────────────────────────────────────────
        theta_decay_pct: float | None = None
        if theta is not None and current_price > 0:
            theta_decay_pct = abs(theta) / (current_price * 100)

        # ── Alert priority (first match wins) ─────────────────────────────────
        alert: str | None = None
        if dte == 0 and now.hour >= 19:  # 3 PM ET == 19:00 UTC (approximate)
            alert = "NEAR_EXPIRY"
        elif 0 < open_interest < self.LOW_OI_THRESHOLD:
            alert = "LOW_OI"
        elif spread_pct > self.SPREAD_ALERT_PCT:
            alert = "WIDE_SPREAD"
        elif theta_decay_pct is not None and theta_decay_pct > self.THETA_DECAY_ALERT_PCT:
            alert = "HIGH_THETA_DECAY"

        return PositionGreeks(
            position_id=pos.position_id,
            symbol=pos.symbol,
            direction=pos.direction,
            strike=pos.strike,
            expiry=str(pos.expiry),
            current_price=current_price,
            entry_price=entry_price,
            pnl_per_share=pnl_per_share,
            pnl_pct=pnl_pct,
            pnl_per_contract=pnl_per_contract,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            implied_volatility=implied_volatility,
            days_to_expiry=dte,
            theta_decay_pct=theta_decay_pct,
            bid=bid,
            ask=ask,
            spread_pct=spread_pct,
            volume=volume,
            open_interest=open_interest,
            updated_at=now.isoformat(),
            account_id=getattr(pos, "account_id", "primary"),
            alert=alert,
        )

    def _write_greeks_file(self, greeks: list[PositionGreeks]) -> None:
        """Atomically write the greeks list to GREEKS_FILE."""
        GREEKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = GREEKS_FILE.with_suffix(".tmp")
        payload = [asdict(g) for g in greeks]
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        tmp.replace(GREEKS_FILE)

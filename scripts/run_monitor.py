"""
scripts/run_monitor.py — Launch the Monitor Agent.

Creates a MonitorAgent with a stub RHGateway and empty sell queues,
then runs it until KeyboardInterrupt.

In production, wire in the real RHGateway and pass sell_queues from
the Discord gateway listener.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Stub gateway for standalone run ────────────────────────────────────────

class _StubRHGateway:
    """Minimal stub — logs instead of sending real orders."""

    paper_mode = True

    async def get_quote(
        self,
        symbol: str,
        direction: str,
        strike: float,
        expiry: Any,
    ) -> float | None:
        logger.debug("get_quote(%s %s %.0f %s) -> None (stub)", symbol, direction, strike, expiry)
        return None  # MonitorAgent will use paper-mode drift

    async def close_position(self, position: Any, qty: int, reason: str) -> bool:
        logger.info(
            "[STUB] close_position: %s %s %.0f qty=%d reason=%s",
            position.symbol, position.direction, position.strike, qty, reason,
        )
        return True


# ─── Entry point ─────────────────────────────────────────────────────────────

async def main() -> None:
    from gateway.monitor_agent import MonitorAgent

    gateway = _StubRHGateway()
    sell_queues: dict[str, asyncio.Queue] = {}

    agent = MonitorAgent(
        gateway=gateway,
        sell_queues=sell_queues,
        poll_interval_seconds=30,
    )

    logger.info("Starting MonitorAgent (paper_mode=%s)", gateway.paper_mode)
    await agent.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("MonitorAgent stopped by user")

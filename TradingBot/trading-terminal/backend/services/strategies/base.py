"""Base class for all trading strategy agents."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class AgentStrategyBase(ABC):
    """
    Abstract base for all trading strategy agents.

    Each agent runs in a continuous loop scanning for opportunities.
    When a signal is generated, it calls self.emit_signal() which
    enqueues to the Robinhood execution service.
    """

    # Override in subclass
    AGENT_ID: str = "base_agent"
    DISPLAY_NAME: str = "Base Agent"
    CATEGORY: str = "ALGORITHM"
    SCAN_INTERVAL_SEC: int = 300  # 5 min default

    def __init__(self) -> None:
        self._running = False
        self._signals_emitted = 0
        self._last_scan: datetime | None = None

    @abstractmethod
    async def scan(self) -> list[dict[str, Any]]:
        """
        Scan for trading opportunities.
        Return list of signal dicts, or empty list if no signal.

        Each signal dict must have:
        {
          "ticker": str,
          "side": "long" | "short",
          "option_type": "call" | "put" | None,
          "strike": float | None,
          "expiry": str | None,  # YYYY-MM-DD
          "quantity": int,
          "confidence": float,   # 0.0 - 1.0
          "stop_loss_pct": float,
          "take_profit_pct": float,
          "rationale": str,
        }
        """
        ...

    async def emit_signal(self, signal: dict[str, Any]) -> None:
        """Send signal to Robinhood execution queue."""
        from ..robinhood_execution_service import get_execution_service
        svc = get_execution_service()
        if not svc:
            logger.warning("[%s] Execution service not available — signal dropped", self.AGENT_ID)
            return

        signal["agent_id"] = self.AGENT_ID
        signal.setdefault("priority", 5)
        self._signals_emitted += 1

        msg_id = await svc.enqueue(signal)
        logger.info(
            "[%s] Signal emitted: %s %s/%s confidence=%.0f%% msg_id=%s",
            self.AGENT_ID, signal.get("ticker"), signal.get("option_type"),
            signal.get("strike"), signal.get("confidence", 0) * 100, msg_id[:8]
        )

    async def run(self) -> None:
        """Main loop — runs until stopped."""
        self._running = True
        logger.info("[%s] Strategy agent started (interval=%ds)", self.AGENT_ID, self.SCAN_INTERVAL_SEC)
        while self._running:
            try:
                self._last_scan = datetime.now(timezone.utc)
                signals = await self.scan()
                for signal in signals:
                    await self.emit_signal(signal)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[%s] Scan error: %s", self.AGENT_ID, e)
            await asyncio.sleep(self.SCAN_INTERVAL_SEC)

    def stop(self) -> None:
        self._running = False

    def status(self) -> dict[str, Any]:
        return {
            "agent_id": self.AGENT_ID,
            "display_name": self.DISPLAY_NAME,
            "category": self.CATEGORY,
            "running": self._running,
            "signals_emitted": self._signals_emitted,
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "scan_interval_sec": self.SCAN_INTERVAL_SEC,
        }


__all__ = ["AgentStrategyBase"]

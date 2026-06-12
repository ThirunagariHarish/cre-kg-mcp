"""
core/base_analyst.py — BaseAnalyst: the universal analyst template.

Every analyst (Vinod, Mag7, Technical, etc.) inherits from this class.
The template enforces:
  1. Heartbeat starts FIRST before any other async work
  2. Kill switch checked before emitting any signal
  3. Standard signal emission to a shared asyncio.Queue
  4. Consistent error handling and logging

Analysts implement three methods:
  - gather_data(trigger) → raw data from their source
  - build_evidence(raw_data) → list[Evidence]
  - select_contract(evidence) → OptionContract | None
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from core.kill_switch import is_blocked
from core.logging import TradeEvent, journal
from core.redis_client import heartbeat_loop
from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    OptionDirection,
    RiskLevel,
    SourceLayer,
    TradeSignal,
    WakeTrigger,
)

logger = logging.getLogger(__name__)


class WakeEvent:
    """Payload passed to wake() — carries the trigger type and raw input."""

    def __init__(
        self,
        trigger: WakeTrigger,
        raw: Any = None,
        channel_id: str | None = None,
    ) -> None:
        self.trigger: WakeTrigger = trigger
        self.raw: Any = raw          # Discord message, UW alert, etc.
        self.channel_id: str | None = channel_id
        self.received_at: datetime = datetime.now(tz=timezone.utc)


class BaseAnalyst(ABC):
    """
    Abstract base for all analysts.

    Subclass and implement: gather_data, build_evidence, select_contract.
    The framework handles: heartbeat, kill switch, dedup, signal emission.
    """

    def __init__(
        self,
        analyst_id: str,
        source_layer: SourceLayer,
        exit_rules: ExitRules,
        signal_queue: "asyncio.Queue[TradeSignal]",
        *,
        wake_trigger: WakeTrigger = "SCHEDULE",
        wake_interval_seconds: int = 300,
        min_evidence_items: int = 2,
        confidence_threshold: float = 0.60,  # float, not int — legacy lesson
    ) -> None:
        self.analyst_id = analyst_id
        self.source_layer = source_layer
        self.exit_rules = exit_rules
        self.signal_queue = signal_queue
        self.wake_trigger = wake_trigger
        self.wake_interval_seconds = wake_interval_seconds
        self.min_evidence_items = min_evidence_items
        self.confidence_threshold = confidence_threshold  # 0.0–1.0

        self._log = logging.getLogger(f"analyst.{analyst_id}")
        self._running = False
        self._seen_signal_keys: set[str] = set()  # in-process dedup

    # ─── Template methods (subclasses implement these) ───────────────────

    @abstractmethod
    async def gather_data(self, trigger: WakeEvent) -> Any:
        """Fetch raw data from this analyst's data source(s)."""
        ...

    @abstractmethod
    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        """
        Convert raw data into Evidence items.
        Return [] if there's nothing worth trading on.
        """
        ...

    @abstractmethod
    async def select_contract(
        self,
        evidence: list[Evidence],
        raw_data: Any,
    ) -> OptionContract | None:
        """
        Given sufficient evidence, pick the specific option contract.
        Return None if no suitable contract is available.
        """
        ...

    def compute_confidence(self, evidence: list[Evidence]) -> float:
        """
        Default confidence = weighted bullish score.
        Subclasses can override for custom logic.
        """
        total = sum(e.weight for e in evidence)
        if total == 0:
            return 0.0
        bullish = sum(e.weight for e in evidence if e.bullish)
        return bullish / total

    def compute_risk_level(self, evidence: list[Evidence]) -> RiskLevel:
        """Default risk assessment from evidence weights."""
        confidence = self.compute_confidence(evidence)
        if confidence >= 0.80:
            return "LOW"
        if confidence >= 0.60:
            return "MEDIUM"
        return "HIGH"

    # ─── Framework methods (do not override unless necessary) ────────────

    async def run(self) -> None:
        """
        Main entry point. Start heartbeat FIRST, then the wake loop.
        Legacy lesson: heartbeat must be started before any other awaitable
        to avoid deadlock scenarios.
        """
        self._running = True
        self._log.info("Analyst starting: %s (trigger=%s)", self.analyst_id, self.wake_trigger)

        # HEARTBEAT FIRST — non-negotiable ordering
        asyncio.create_task(
            heartbeat_loop(self.analyst_id, interval_seconds=30),
            name=f"heartbeat_{self.analyst_id}",
        )

        if self.wake_trigger == "SCHEDULE":
            await self._schedule_loop()
        # For DISCORD_MESSAGE and MARKET_EVENT, the caller pushes WakeEvents
        # via wake(). The analyst doesn't self-schedule.

    async def wake(self, event: WakeEvent) -> None:
        """
        Called externally (e.g. Discord Gateway) when a relevant message arrives.
        Also used internally by the schedule loop.
        """
        if not self._running:
            return

        self._log.debug("Woken by %s", event.trigger)
        try:
            await self._process(event)
        except Exception as exc:
            self._log.exception("Unhandled error in analyst %s: %s", self.analyst_id, exc)

    async def stop(self) -> None:
        self._running = False
        self._log.info("Analyst stopped: %s", self.analyst_id)

    # ─── Internal ────────────────────────────────────────────────────────

    async def _schedule_loop(self) -> None:
        while self._running:
            await self._process(WakeEvent(trigger="SCHEDULE"))
            await asyncio.sleep(self.wake_interval_seconds)

    async def _process(self, trigger: WakeEvent) -> None:
        # 1. Kill switch — check before doing any work
        if is_blocked():
            self._log.warning("Kill switch active — skipping wake cycle")
            journal(
                TradeEvent.KILL_SWITCH_BLOCKED,
                self.analyst_id,
                "none",
                extra={"trigger": trigger.trigger},
            )
            return

        # 2. Gather data from this analyst's sources
        try:
            raw_data = await self.gather_data(trigger)
        except Exception as exc:
            self._log.error("gather_data failed: %s", exc)
            return

        if raw_data is None:
            self._log.debug("No data returned — skipping cycle")
            return

        # 3. Build evidence
        evidence = await self.build_evidence(raw_data)

        if len(evidence) < self.min_evidence_items:
            self._log.debug(
                "Insufficient evidence (%d/%d items) — no signal",
                len(evidence), self.min_evidence_items,
            )
            return

        confidence = self.compute_confidence(evidence)
        if confidence < self.confidence_threshold:
            self._log.debug(
                "Confidence %.2f below threshold %.2f — no signal",
                confidence, self.confidence_threshold,
            )
            return

        # 4. Select the specific contract
        contract = await self.select_contract(evidence, raw_data)
        if contract is None:
            self._log.info("Evidence sufficient but no tradable contract found")
            return

        # 5. Build the TradeSignal
        direction: OptionDirection = self._infer_direction(evidence)
        signal = TradeSignal(
            analyst_id=self.analyst_id,
            source_layer=self.source_layer,
            timestamp=datetime.now(tz=timezone.utc),
            symbol=contract.symbol,
            direction=direction,
            strike=contract.strike,
            expiry=contract.expiry,
            signal_price=contract.mark_per_share,
            evidence=evidence,
            risk_level=self.compute_risk_level(evidence),
            confidence=confidence,
            exit_rules=self.exit_rules,
            source_metadata={
                "raw_trigger": str(trigger.raw)[:500] if trigger.raw else None,
                "channel_id": trigger.channel_id,
            },
        )

        # 6. Dedup — same symbol + expiry + direction from this analyst within 5 min
        dedup_key = f"{self.analyst_id}:{contract.symbol}:{contract.expiry}:{direction}"
        if dedup_key in self._seen_signal_keys:
            self._log.info("Duplicate signal suppressed: %s", dedup_key)
            journal(
                TradeEvent.DUPLICATE_SIGNAL_DROPPED,
                self.analyst_id,
                signal.signal_id,
                extra={"dedup_key": dedup_key},
            )
            return

        self._seen_signal_keys.add(dedup_key)
        # Clear dedup after 5 minutes via task
        asyncio.create_task(self._clear_dedup(dedup_key, delay=300))

        # 7. Emit to Master Analyst queue
        await self.signal_queue.put(signal)
        journal(
            TradeEvent.SIGNAL_EMITTED,
            self.analyst_id,
            signal.signal_id,
            extra={
                "symbol": signal.symbol,
                "direction": signal.direction,
                "strike": signal.strike,
                "expiry": str(signal.expiry),
                "confidence": signal.confidence,
                "evidence_count": len(evidence),
            },
        )
        self._log.info(
            "Signal emitted: %s %s %s@%.1f exp=%s conf=%.2f",
            signal.symbol, signal.direction, signal.direction,
            signal.strike, signal.expiry, signal.confidence,
        )

    def _infer_direction(self, evidence: list[Evidence]) -> OptionDirection:
        """Infer CALL vs PUT from bullish/bearish evidence balance."""
        bullish_w = sum(e.weight for e in evidence if e.bullish)
        bearish_w = sum(e.weight for e in evidence if not e.bullish)
        return "CALL" if bullish_w >= bearish_w else "PUT"

    async def _clear_dedup(self, key: str, delay: int) -> None:
        await asyncio.sleep(delay)
        self._seen_signal_keys.discard(key)

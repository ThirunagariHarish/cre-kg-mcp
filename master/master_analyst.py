"""
master/master_analyst.py — MasterAnalyst: the gatekeeper between analysts and the RH Gateway.

Responsibilities:
  1. Consume TradeSignal objects from a shared asyncio.Queue
  2. Deduplicate signals from the same analyst for the same contract within 5 minutes
  3. Check the kill switch before every approval attempt
  4. Ask Claude LLM to approve or reject each signal
  5. Log ALL rejections to the trade journal (never silent)
  6. Forward approved signals to the gateway queue

Design contracts:
  - is_blocked() True → signal rejected immediately, no LLM call
  - Duplicate within 300s → dropped with journal entry
  - LLM returns APPROVE → signal forwarded to gateway_queue
  - LLM returns REJECT → signal rejected with reason logged
  - CancelledError → clean shutdown, no crash
  - Pattern auto-rejected if RL gate: win_rate < 40% with >= 10 trades
  - Conflicting signals (opposite direction, same symbol, within 30 min) are rejected
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic

from core.kill_switch import is_blocked
from core.logging import TradeEvent, journal
from core.schemas import TradeSignal
from master.memory_journal import MemoryJournal, _compute_pattern_type

logger = logging.getLogger(__name__)

# Dedup window: same (analyst_id|symbol|strike|expiry|direction) within this window is dropped
_DEDUP_WINDOW_SECONDS = 300

# Conflict detection window: opposite-direction signals for the same symbol within this window
_CONFLICT_WINDOW_SECONDS = 1800  # 30 minutes


class MasterAnalyst:
    """
    Sits between all analysts and the RH Gateway.

    Consumes from signal_queue, applies dedup + kill switch + LLM review,
    and emits approved signals to gateway_queue.
    """

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        gateway_queue: "asyncio.Queue[TradeSignal]",
        *,
        paper_mode: bool = True,
    ) -> None:
        self.signal_queue = signal_queue
        self.gateway_queue = gateway_queue
        self.paper_mode = paper_mode

        self._client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
        self._model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

        # Dedup store: key -> datetime when signal was first seen
        self._seen: dict[str, datetime] = {}

        # Conflict detection: last approved signal per symbol
        # key = symbol, value = (signal, approved_at)
        self._recently_approved: dict[str, tuple[TradeSignal, datetime]] = {}

        # Memory journal for RL gate and win-rate tracking
        self._journal = MemoryJournal()
        self._journal_initialized = False

        # Counters for observability
        self._approved_count = 0
        self._rejected_count = 0
        self._duplicate_count = 0

        # Consensus gate
        self._consensus_threshold = 1  # default: no consensus required
        self._pending_consensus: dict[str, list[TradeSignal]] = {}
        try:
            import json as _json
            _cfg_path = os.path.join(os.path.dirname(__file__), "..", "configs", "global.json")
            with open(_cfg_path) as _f:
                _gcfg = _json.load(_f)
            _ct = _gcfg.get("master_analyst", {}).get("consensus_threshold")
            if _ct is not None:
                self._consensus_threshold = int(_ct)
        except Exception:
            pass  # use default of 1

        self._log = logging.getLogger("master_analyst")

    # ─── Public API ──────────────────────────────────────────────────────────

    async def _ensure_journal_initialized(self) -> None:
        """Lazy-initialize the memory journal on first use."""
        if not self._journal_initialized:
            await self._journal.initialize()
            self._journal_initialized = True

    async def run(self) -> None:
        """
        Main loop — runs until cancelled.
        Processes one signal at a time from the input queue.
        """
        await self._ensure_journal_initialized()
        self._log.info(
            "MasterAnalyst starting (model=%s, paper_mode=%s)",
            self._model,
            self.paper_mode,
        )
        try:
            while True:
                signal = await self.signal_queue.get()
                try:
                    await self._process(signal)
                except Exception as exc:
                    self._log.exception(
                        "Unhandled error processing signal %s: %s",
                        signal.signal_id,
                        exc,
                    )
                finally:
                    self.signal_queue.task_done()
        except asyncio.CancelledError:
            self._log.info(
                "MasterAnalyst shutting down — approved=%d rejected=%d duplicates=%d",
                self._approved_count,
                self._rejected_count,
                self._duplicate_count,
            )
            raise

    # ─── Internal pipeline ───────────────────────────────────────────────────

    async def _process(self, signal: TradeSignal) -> None:
        """Full processing pipeline for one signal."""

        # 0. Paused analyst check (before dedup — paused analysts are always dropped first)
        from gateway.telegram_handler import _load_paused_analysts
        if signal.analyst_id in _load_paused_analysts():
            await self._reject(signal, f"Analyst {signal.analyst_id} is paused")
            return

        # 1. Dedup check
        if self._is_duplicate(signal):
            self._duplicate_count += 1
            self._log.info(
                "Duplicate signal dropped: analyst=%s symbol=%s strike=%s expiry=%s dir=%s",
                signal.analyst_id,
                signal.symbol,
                signal.strike,
                signal.expiry,
                signal.direction,
            )
            journal(
                TradeEvent.DUPLICATE_SIGNAL_DROPPED,
                signal.analyst_id,
                signal.signal_id,
                extra={
                    "symbol": signal.symbol,
                    "strike": signal.strike,
                    "expiry": str(signal.expiry),
                    "direction": signal.direction,
                    "dedup_key": self._dedup_key(signal),
                },
            )
            return

        # Record dedup entry now (before any async ops so concurrent signals are caught)
        self._seen[self._dedup_key(signal)] = datetime.now(tz=timezone.utc)

        # 2. Kill switch check
        if is_blocked():
            await self._reject(signal, "Kill switch is active — trading halted")
            journal(
                TradeEvent.KILL_SWITCH_BLOCKED,
                signal.analyst_id,
                signal.signal_id,
                extra={"symbol": signal.symbol, "direction": signal.direction},
            )
            return

        # 3b. VIX regime filter
        from core.vix_regime import adjust_confidence_threshold, get_regime_label, should_pause_high_risk_analysts
        vix_label = get_regime_label()
        adjusted_threshold = adjust_confidence_threshold(signal.confidence)
        if signal.confidence < adjusted_threshold:
            await self._reject(
                signal,
                f"VIX regime filter ({vix_label}): confidence {signal.confidence:.0%} < adjusted threshold {adjusted_threshold:.0%}",
            )
            return
        if signal.risk_level == "HIGH" and should_pause_high_risk_analysts():
            await self._reject(signal, "VIX CRISIS regime: HIGH risk signals paused")
            return

        # 3. RL gate: auto-reject patterns with win_rate < 40% (>= 10 trades)
        await self._ensure_journal_initialized()
        pattern_type = _compute_pattern_type(signal)
        rl_reject = await self._journal.should_reject_pattern(signal.analyst_id, pattern_type)
        if rl_reject:
            await self._reject(signal, "Pattern auto-rejected: win_rate < 40% (RL gate)")
            return

        # 4. Conflict detection: opposite direction for same symbol within 30 min
        conflict_reason = self._check_conflict(signal)
        if conflict_reason is not None:
            await self._reject(signal, conflict_reason)
            return

        # 5. Consensus gate (only active if threshold > 1)
        if self._consensus_threshold > 1:
            key = f"{signal.symbol}|{signal.direction}"
            now = datetime.now(tz=timezone.utc)
            # Clean stale entries (older than 15 min)
            if key in self._pending_consensus:
                self._pending_consensus[key] = [
                    s for s in self._pending_consensus[key]
                    if (now - s.timestamp).total_seconds() < 900
                ]
            else:
                self._pending_consensus[key] = []
            # Avoid adding duplicates from the same analyst
            existing_analysts = {s.analyst_id for s in self._pending_consensus[key]}
            if signal.analyst_id not in existing_analysts:
                self._pending_consensus[key].append(signal)
            count = len(self._pending_consensus[key])
            if count < self._consensus_threshold:
                self._log.info(
                    "Consensus gate: %d/%d analysts agree on %s %s — waiting",
                    count, self._consensus_threshold, signal.symbol, signal.direction,
                )
                return  # Hold signal; don't reject, don't approve yet
            else:
                self._log.info(
                    "Consensus reached: %d analysts agree on %s %s — proceeding",
                    count, signal.symbol, signal.direction,
                )
                self._pending_consensus.pop(key, None)  # Clear after consensus reached

        # Ask Claude (with win-rate hint)
        approved, reason = await self._ask_claude(signal)

        if approved:
            self._approved_count += 1
            self._log.info(
                "Signal APPROVED: %s %s %s@%.1f conf=%.2f reason=%s",
                signal.analyst_id,
                signal.symbol,
                signal.direction,
                signal.strike,
                signal.confidence,
                reason,
            )
            journal(
                TradeEvent.SIGNAL_APPROVED,
                signal.analyst_id,
                signal.signal_id,
                extra={
                    "symbol": signal.symbol,
                    "direction": signal.direction,
                    "strike": signal.strike,
                    "expiry": str(signal.expiry),
                    "confidence": signal.confidence,
                    "reason": reason,
                    "paper_mode": self.paper_mode,
                },
            )
            # Track this approved signal for conflict detection
            self._recently_approved[signal.symbol] = (signal, datetime.now(tz=timezone.utc))
            await self.gateway_queue.put(signal)
        else:
            await self._reject(signal, reason)

    async def _ask_claude(self, signal: TradeSignal) -> tuple[bool, str]:
        """
        Call Claude to approve or reject a signal.
        Returns (approved: bool, reason: str).

        Safe-fail: any error → reject with error reason logged.
        """
        # Fetch analyst win rate for prompt enrichment
        win_rate = await self._journal.get_analyst_win_rate(signal.analyst_id)
        prompt = _build_prompt(signal, win_rate=win_rate)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            self._log.debug("Claude response for %s: %s", signal.signal_id, text)

            return _parse_claude_response(text)

        except anthropic.APIError as exc:
            reason = f"Claude API error: {exc}"
            self._log.error("Claude API error for signal %s: %s", signal.signal_id, exc)
            return False, reason
        except Exception as exc:
            reason = f"Unexpected error calling Claude: {exc}"
            self._log.exception("Unexpected Claude error for signal %s", signal.signal_id)
            return False, reason

    def _dedup_key(self, signal: TradeSignal) -> str:
        """Composite key for deduplication."""
        return f"{signal.analyst_id}|{signal.symbol}|{signal.strike}|{signal.expiry}|{signal.direction}"

    def _is_duplicate(self, signal: TradeSignal) -> bool:
        """
        True if the same (analyst, symbol, strike, expiry, direction) was seen
        within the dedup window.

        Also evicts expired entries to prevent unbounded growth.
        """
        key = self._dedup_key(signal)
        now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(seconds=_DEDUP_WINDOW_SECONDS)

        # Evict stale entries while we're here
        stale = [k for k, ts in self._seen.items() if ts < cutoff]
        for k in stale:
            del self._seen[k]

        if key in self._seen:
            seen_at = self._seen[key]
            if seen_at >= cutoff:
                return True

        return False

    def _check_conflict(self, signal: TradeSignal) -> str | None:
        """
        Detect conflicting signals: opposite direction for the same symbol
        from any analyst within the last 30 minutes.

        Returns a conflict reason string if a conflict is detected, else None.
        Evicts stale entries while checking.
        """
        now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(seconds=_CONFLICT_WINDOW_SECONDS)

        # Evict stale entries
        stale_symbols = [
            sym for sym, (_, approved_at) in self._recently_approved.items()
            if approved_at < cutoff
        ]
        for sym in stale_symbols:
            del self._recently_approved[sym]

        if signal.symbol not in self._recently_approved:
            return None

        other_signal, approved_at = self._recently_approved[signal.symbol]

        # Only flag if directions are opposite
        if other_signal.direction == signal.direction:
            return None

        conflict_msg = (
            f"CONFLICT: {signal.analyst_id} {signal.direction} vs "
            f"{other_signal.analyst_id} {other_signal.direction} on {signal.symbol}"
        )
        self._log.warning(conflict_msg)
        return conflict_msg

    async def _reject(self, signal: TradeSignal, reason: str) -> None:
        """Log rejection to journal and increment counter. Always non-silent."""
        self._rejected_count += 1
        self._log.info(
            "Signal REJECTED: %s %s %s@%.1f — %s",
            signal.analyst_id,
            signal.symbol,
            signal.direction,
            signal.strike,
            reason,
        )
        journal(
            TradeEvent.SIGNAL_REJECTED,
            signal.analyst_id,
            signal.signal_id,
            extra={
                "symbol": signal.symbol,
                "direction": signal.direction,
                "strike": signal.strike,
                "expiry": str(signal.expiry),
                "confidence": signal.confidence,
                "rejection_reason": reason,
                "paper_mode": self.paper_mode,
            },
        )


# ─── Helpers (module-level, easily testable) ─────────────────────────────────

def _build_prompt(signal: TradeSignal, *, win_rate: float | None = None) -> str:
    """Build the Claude prompt for a given signal.

    win_rate — if provided, a performance hint is injected so Claude can weight
    the analyst's historical accuracy when making its decision.
    """
    cost_per_contract = signal.signal_price * 100

    # Build analyst performance hint
    if win_rate is not None:
        win_pct = win_rate * 100
        if win_rate > 0.60:
            performance_hint = f"High performer (win rate: {win_pct:.0f}%)"
        elif win_rate < 0.40:
            performance_hint = f"Low performer (win rate: {win_pct:.0f}%) — be skeptical"
        else:
            performance_hint = f"Average performer (win rate: {win_pct:.0f}%)"
        analyst_line = f"Signal from: {signal.analyst_id} [{performance_hint}]"
    else:
        analyst_line = f"Signal from: {signal.analyst_id} [insufficient history]"

    return (
        "You are a risk-aware trading analyst reviewing a signal before execution.\n"
        f"{analyst_line}\n"
        f"Symbol: {signal.symbol} {signal.direction} {signal.strike} expiring {signal.expiry}\n"
        f"Signal price: ${signal.signal_price}/contract x100 = ${cost_per_contract:.0f}/contract\n"
        f"Confidence: {signal.confidence:.0%}\n"
        f"Evidence:\n{signal.evidence_summary()}\n\n"
        "Respond with exactly:\n"
        "APPROVE - {reason}\n"
        "or\n"
        "REJECT - {reason}"
    )


def _parse_claude_response(text: str) -> tuple[bool, str]:
    """
    Parse Claude's response text for APPROVE or REJECT keyword.

    Accepts any case and any position in the first line.
    Returns (approved, reason).
    """
    first_line = text.split("\n")[0].strip()
    upper = first_line.upper()

    if upper.startswith("APPROVE"):
        # Extract reason after "APPROVE" and optional " - " separator
        parts = first_line.split("-", 1)
        reason = parts[1].strip() if len(parts) > 1 else "approved"
        return True, reason

    if upper.startswith("REJECT"):
        parts = first_line.split("-", 1)
        reason = parts[1].strip() if len(parts) > 1 else "rejected"
        return False, reason

    # Ambiguous response — safe-fail to reject
    return False, f"Claude response did not contain APPROVE or REJECT: {first_line[:120]}"

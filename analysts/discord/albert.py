"""
analysts/discord/albert.py — Albert Earnings Trader analyst.

Albert trades earnings plays — option buys around earnings season.
Exit strategy: MANUAL (human closes via dashboard or Telegram command).

Message format (confirmed pattern):
  Bought AAPL 210C at 3.50
  Bougth NVDA 900P at 6.20  (typo variant)

Earnings gate:
  - Checks shared/state/earnings_calendar.json for upcoming/recent earnings
  - Fail-open: if file missing or symbol not listed, trade is allowed
  - Gate considers within ±14 days of earnings date

Analyst ID: "albert"
Source layer: DISCORD
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.base_analyst import BaseAnalyst, WakeEvent
from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    OptionDirection,
    TradeSignal,
)

logger = logging.getLogger("analyst.albert")

# ─── Author ───────────────────────────────────────────────────────────────────

# Buys are posted by a bot whose username contains "albert" (case-insensitive).
_BUY_AUTHOR_FRAGMENT = "albert"

# ─── Regex patterns ───────────────────────────────────────────────────────────

# BUY pattern — handles both "Bought" and "Bougth" typo:
# Bought AAPL 210C at 3.50
# Bougth NVDA 900P at 6.20 Earnings play
_ALBERT_BUY_RE = re.compile(
    r"Boug(?:ht|th)\s+([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CP])\s+at\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# ─── Earnings calendar path ───────────────────────────────────────────────────

_EARNINGS_CALENDAR_PATH = Path("shared/state/earnings_calendar.json")
_EARNINGS_WINDOW_DAYS = 14  # ±14 days from earnings date


# ─── Parsed message dataclass ─────────────────────────────────────────────────

@dataclass
class BuySignal:
    symbol: str
    direction: OptionDirection
    strike: float
    price: float
    expiry: date | None       # None if not specified in message
    channel_id: str
    message_id: str
    raw_content: str


# ─── Pure parser functions (testable without Discord) ────────────────────────

def parse_albert_buy(msg: dict) -> BuySignal | None:
    """
    Parse an Albert earnings buy message. Returns None if not an Albert buy.

    Accepts messages from authors whose name contains "albert" (case-insensitive)
    and that are posted by a bot. Parses the standard buy format:
      Bought {SYMBOL} {strike}{C/P} at {price}
    Also handles the "Bougth" typo variant.
    """
    if not _is_albert_author(msg):
        return None

    content = msg.get("content", "")
    m = _ALBERT_BUY_RE.search(content)
    if not m:
        return None

    symbol = m.group(1).upper()
    strike = float(m.group(2))
    direction: OptionDirection = "CALL" if m.group(3).upper() == "C" else "PUT"
    price = float(m.group(4))

    return BuySignal(
        symbol=symbol,
        direction=direction,
        strike=strike,
        price=price,
        expiry=None,  # Albert messages don't include expiry by default
        channel_id=msg.get("channel_id", ""),
        message_id=msg.get("message_id", ""),
        raw_content=content,
    )


def is_earnings_period(symbol: str) -> bool:
    """
    Check if the given symbol has earnings within ±14 days of today.

    Reads shared/state/earnings_calendar.json. If the file is missing,
    unreadable, or the symbol is not listed, returns True (fail-open).

    Calendar format: {"AAPL": "2026-07-25", "MSFT": "2026-07-22", ...}
    """
    try:
        raw = _EARNINGS_CALENDAR_PATH.read_text(encoding="utf-8")
        calendar: dict[str, str] = json.loads(raw)
    except FileNotFoundError:
        logger.debug(
            "Earnings calendar not found at %s — fail-open, allowing trade",
            _EARNINGS_CALENDAR_PATH,
        )
        return True
    except Exception as exc:
        logger.warning(
            "Failed to read earnings calendar: %s — fail-open, allowing trade", exc
        )
        return True

    earnings_date_str = calendar.get(symbol.upper())
    if earnings_date_str is None:
        logger.debug(
            "Symbol %s not in earnings calendar — fail-open, allowing trade", symbol
        )
        return True

    try:
        earnings_date = date.fromisoformat(earnings_date_str)
    except ValueError:
        logger.warning(
            "Invalid earnings date '%s' for %s — fail-open, allowing trade",
            earnings_date_str,
            symbol,
        )
        return True

    today = datetime.now(tz=timezone.utc).date()
    delta = abs((earnings_date - today).days)
    within_window = delta <= _EARNINGS_WINDOW_DAYS

    logger.info(
        "Earnings gate check: %s earnings=%s today=%s delta=%d days within_window=%s",
        symbol,
        earnings_date,
        today,
        delta,
        within_window,
    )
    return within_window


# ─── Author check ─────────────────────────────────────────────────────────────

def _is_albert_author(msg: dict) -> bool:
    name = (msg.get("author_global_name") or msg.get("author_name") or "").lower()
    return _BUY_AUTHOR_FRAGMENT in name and msg.get("is_bot", False)


# ─── AlbertAnalyst ────────────────────────────────────────────────────────────

class AlbertAnalyst(BaseAnalyst):
    """
    Listens to Albert's Discord channel for earnings option plays.
    Exit: MANUAL — human closes via dashboard or Telegram command.

    Earnings gate:
      - Checks shared/state/earnings_calendar.json for ±14 day window
      - Fail-open: if file missing or symbol not listed, trade is allowed

    Buffers:
      - execution_buffer_pct (0.20): RH limit order price = signal_price × 1.20
    """

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        channel_id: str,
        *,
        execution_buffer_pct: float = 0.20,
        max_premium_usd: float = 800.0,
        confidence_threshold: float = 0.70,
    ) -> None:
        exit_rules = ExitRules(strategy="MANUAL")
        super().__init__(
            analyst_id="albert",
            source_layer="DISCORD",
            exit_rules=exit_rules,
            signal_queue=signal_queue,
            wake_trigger="DISCORD_MESSAGE",
            min_evidence_items=1,
            confidence_threshold=confidence_threshold,
        )
        self._channel_id = channel_id
        self._execution_buffer_pct = execution_buffer_pct
        self._max_premium_usd = max_premium_usd
        self._msg_queue: asyncio.Queue[dict] = asyncio.Queue()

    @property
    def message_queue(self) -> "asyncio.Queue[dict]":
        """The gateway puts Discord messages here."""
        return self._msg_queue

    async def run(self) -> None:
        self._running = True
        self._log.info("AlbertAnalyst starting")
        import core.redis_client as rc
        asyncio.create_task(
            rc.heartbeat_loop(self.analyst_id, interval_seconds=30),
            name=f"heartbeat_{self.analyst_id}",
        )
        asyncio.create_task(self._consume_messages())

    async def _consume_messages(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self._msg_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

            event = WakeEvent(
                trigger="DISCORD_MESSAGE",
                raw=msg,
                channel_id=msg.get("channel_id"),
            )
            await self.wake(event)

    # ─── BaseAnalyst abstract methods ─────────────────────────────────────

    async def gather_data(self, trigger: WakeEvent) -> Any:
        msg = trigger.raw
        if not isinstance(msg, dict):
            return None
        return parse_albert_buy(msg)

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        if raw_data is None:
            return []

        buy: BuySignal = raw_data
        premium = buy.price * 100
        in_earnings_window = is_earnings_period(buy.symbol)

        evidence = [
            Evidence(
                indicator="albert_buy_signal",
                value=buy.raw_content[:200],
                interpretation=(
                    f"Albert bought {buy.symbol} {buy.strike}{buy.direction[0]} "
                    f"at ${buy.price}"
                ),
                weight=0.85,
                bullish=(buy.direction == "CALL"),
            ),
            Evidence(
                indicator="earnings_gate",
                value=in_earnings_window,
                interpretation=(
                    f"{buy.symbol} {'IS' if in_earnings_window else 'is NOT'} within "
                    f"{_EARNINGS_WINDOW_DAYS}-day earnings window"
                ),
                weight=0.10,
                bullish=in_earnings_window,
            ),
            Evidence(
                indicator="premium_check",
                value=premium,
                interpretation=(
                    f"Premium ${premium:.0f}/contract — "
                    f"{'within' if premium <= self._max_premium_usd else 'exceeds'} "
                    f"${self._max_premium_usd:.0f} limit"
                ),
                weight=0.05,
                bullish=(premium <= self._max_premium_usd),
            ),
        ]

        return evidence

    async def select_contract(
        self, evidence: list[Evidence], raw_data: Any
    ) -> OptionContract | None:
        if raw_data is None:
            return None

        buy: BuySignal = raw_data

        # Reject if premium exceeds max
        premium = buy.price * 100
        if premium > self._max_premium_usd:
            self._log.info(
                "Signal rejected: premium $%.0f > max $%.0f",
                premium,
                self._max_premium_usd,
            )
            return None

        limit_price = round(buy.price * (1 + self._execution_buffer_pct), 2)
        expiry = buy.expiry or datetime.now(tz=timezone.utc).date()

        return OptionContract(
            symbol=buy.symbol,
            direction=buy.direction,
            strike=buy.strike,
            expiry=expiry,
            bid_per_share=buy.price * 0.95,
            ask_per_share=limit_price,
            mark_per_share=buy.price,
            open_interest=0,
            volume=0,
        )

    def compute_confidence(self, evidence: list[Evidence]) -> float:
        # Albert signals are trusted — fixed high confidence.
        return 0.80

    def _infer_direction(self, evidence: list[Evidence]) -> OptionDirection:  # type: ignore[override]
        # Direction comes from the BuySignal directly in _process.
        return "CALL"

    async def _process(self, trigger: WakeEvent) -> None:
        from core.kill_switch import is_blocked
        from core.logging import TradeEvent, journal

        if is_blocked():
            self._log.warning("Kill switch active — skipping")
            journal(TradeEvent.KILL_SWITCH_BLOCKED, self.analyst_id, "none")
            return

        raw_data = await self.gather_data(trigger)
        if raw_data is None:
            return

        buy: BuySignal = raw_data
        evidence = await self.build_evidence(buy)
        if not evidence:
            return

        # Earnings gate: log but do not block — fail-open by design.
        # If the gate returns False (outside window), we still proceed but log it.
        earnings_evidence = next(
            (e for e in evidence if e.indicator == "earnings_gate"), None
        )
        if earnings_evidence and not earnings_evidence.bullish:
            self._log.info(
                "Earnings gate: %s is outside ±%d day window — proceeding (fail-open)",
                buy.symbol,
                _EARNINGS_WINDOW_DAYS,
            )

        contract = await self.select_contract(evidence, buy)
        if contract is None:
            return

        dedup_key = f"{self.analyst_id}:{buy.symbol}:{buy.strike}:{buy.direction}"
        if dedup_key in self._seen_signal_keys:
            self._log.info("Duplicate buy suppressed: %s", dedup_key)
            return
        self._seen_signal_keys.add(dedup_key)
        asyncio.create_task(self._clear_dedup(dedup_key, delay=300))

        expiry = buy.expiry or datetime.now(tz=timezone.utc).date()
        signal = TradeSignal(
            analyst_id=self.analyst_id,
            source_layer=self.source_layer,
            timestamp=datetime.now(tz=timezone.utc),
            symbol=buy.symbol,
            direction=buy.direction,
            strike=buy.strike,
            expiry=expiry,
            signal_price=buy.price,
            evidence=evidence,
            risk_level="MEDIUM",
            confidence=0.80,
            exit_rules=self.exit_rules,
            source_metadata={
                "message_id": buy.message_id,
                "channel_id": buy.channel_id,
                "raw": buy.raw_content[:300],
                "execution_buffer_pct": self._execution_buffer_pct,
                "earnings_window_days": _EARNINGS_WINDOW_DAYS,
            },
        )

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
            },
        )
        self._log.info(
            "Signal emitted: %s %s %.0f exp=%s @ $%.2f",
            signal.symbol,
            signal.direction,
            signal.strike,
            signal.expiry,
            signal.signal_price,
        )

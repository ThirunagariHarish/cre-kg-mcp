"""
analysts/discord/everest.py — Everest analyst: general trading alerts, MANUAL exit.

Everest posts general option buy alerts. User must manually close via dashboard.
No auto-close is ever triggered — exit strategy is MANUAL.

BUY FORMAT (general):
  "Buying {SYMBOL} {strike}{C/P} at {price}"
  "Added {SYMBOL} {strike}{C/P} exp {date}"
  "{SYMBOL} {strike}{C/P} at {price}" (with @here prefix)
  "Bought {SYMBOL} {strike}{C/P} at {price}"
  "Bougth {SYMBOL} {strike}{C/P} at {price}"  (common typo)

Author filter: any author is accepted (no strict bot filter on Everest server).
Message must have @here OR explicit Buying/Added/Bought/Bougth keyword prefix.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from core.base_analyst import BaseAnalyst, WakeEvent
from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    OptionDirection,
    TradeSignal,
)

logger = logging.getLogger("analyst.everest")

# ─── Regex ────────────────────────────────────────────────────────────────────

# Matches:
#   @here Buying TSLA 430C at 1.70
#   Buying SPY 735P at 2.50
#   Added AAPL 200C at 3.10 exp 06/20
#   Bought NVDA 1200C at 10.50
#   Bougth MSFT 455C at 4.80  (typo handled)
#   @here AMZN 185C at 5.00
# Optional trailing expiry: exp[iry/ires?]? MM/DD[/YY[YY]]
_EVEREST_BUY_RE = re.compile(
    r"(?:@here\s+)?(?:Buy(?:ing)?|Add(?:ed)?|Boug(?:ht|th))\s+"
    r"([A-Z]{1,5})\s+"
    r"(\d+(?:\.\d+)?)\s*([CP])\s+"
    r"(?:at|@)\s+"
    r"(\d+(?:\.\d+)?)"
    r"(?:.*?exp(?:iry|ires?)?\s*:?\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?))?",
    re.IGNORECASE | re.DOTALL,
)

# @here-prefixed bare format: "@here TSLA 430C at 1.70"
_EVEREST_AT_HERE_RE = re.compile(
    r"@here\s+"
    r"([A-Z]{1,5})\s+"
    r"(\d+(?:\.\d+)?)\s*([CP])\s+"
    r"(?:at|@)\s+"
    r"(\d+(?:\.\d+)?)"
    r"(?:.*?exp(?:iry|ires?)?\s*:?\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?))?",
    re.IGNORECASE | re.DOTALL,
)


# ─── Parsed message dataclass ─────────────────────────────────────────────────

@dataclass
class EverestBuySignal:
    symbol: str
    direction: OptionDirection
    strike: float
    price: float
    expiry: date | None      # None means unknown / treat as same-day
    channel_id: str
    message_id: str
    raw_content: str


# ─── Pure parser (testable without Discord) ───────────────────────────────────

def parse_everest_buy(msg: dict) -> EverestBuySignal | None:
    """
    Parse an Everest buy message. Returns None if the message is not a buy alert.

    Accepts messages from any author (no bot filter on Everest server).
    Requires either:
      - An explicit keyword prefix (Buying / Added / Bought / Bougth), OR
      - An @here prefix followed by SYMBOL strike C/P at price.
    """
    content = msg.get("content", "")
    if not content:
        return None

    # Try keyword-prefixed pattern first (most common form)
    m = _EVEREST_BUY_RE.search(content)
    if not m:
        # Try @here-only prefix (no explicit Buy/Add/Bought keyword)
        m = _EVEREST_AT_HERE_RE.search(content)
    if not m:
        return None

    symbol = m.group(1).upper()
    strike = float(m.group(2))
    direction: OptionDirection = "CALL" if m.group(3).upper() == "C" else "PUT"
    price = float(m.group(4))

    expiry: date | None = None
    raw_exp = m.group(5)
    if raw_exp:
        raw_exp = raw_exp.strip()
        today = datetime.now(tz=timezone.utc).date()
        # Try MM/DD/YYYY then MM/DD/YY then MM/DD (inject current year to avoid ambiguity)
        for fmt, raw_to_parse in (
            ("%m/%d/%Y", raw_exp),
            ("%m/%d/%y", raw_exp),
            ("%m/%d/%Y", f"{raw_exp}/{today.year}"),  # MM/DD → MM/DD/YYYY
        ):
            try:
                expiry = datetime.strptime(raw_to_parse, fmt).date()
                break
            except ValueError:
                continue

    return EverestBuySignal(
        symbol=symbol,
        direction=direction,
        strike=strike,
        price=price,
        expiry=expiry,
        channel_id=msg.get("channel_id", ""),
        message_id=msg.get("message_id", ""),
        raw_content=content,
    )


# ─── EverestAnalyst ───────────────────────────────────────────────────────────

class EverestAnalyst(BaseAnalyst):
    """
    Listens to the Everest Discord channel. Emits TradeSignal on every buy alert.
    Exit strategy: MANUAL — user closes via dashboard. No auto-close ever fires.

    Confidence is fixed at 0.70 (Everest is a human posting general alerts;
    no secondary confirmation is available from this source).
    """

    analyst_id = "everest"
    source_layer = "DISCORD"
    exit_rules = ExitRules(strategy="MANUAL")
    confidence_threshold = 0.65

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        channel_id: str,
        *,
        execution_buffer_pct: float = 0.20,
        max_premium_usd: float = 800.0,
        confidence_threshold: float = 0.65,
    ) -> None:
        super().__init__(
            analyst_id=self.analyst_id,
            source_layer=self.source_layer,
            exit_rules=self.exit_rules,
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
        self._log.info("EverestAnalyst starting")
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

    # ─── BaseAnalyst abstract methods ────────────────────────────────────

    async def gather_data(self, trigger: WakeEvent) -> Any:
        msg = trigger.raw
        if not isinstance(msg, dict):
            return None
        return parse_everest_buy(msg)

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        if raw_data is None:
            return []

        buy: EverestBuySignal = raw_data
        premium = buy.price * 100

        evidence = [
            Evidence(
                indicator="everest_buy_signal",
                value=buy.raw_content[:200],
                interpretation=(
                    f"Everest alert: {buy.symbol} {buy.strike}{buy.direction[0]} at ${buy.price}"
                ),
                weight=0.90,
                bullish=(buy.direction == "CALL"),
            ),
            Evidence(
                indicator="premium_check",
                value=premium,
                interpretation=(
                    f"Premium ${premium:.0f}/contract — "
                    f"{'within' if premium <= self._max_premium_usd else 'exceeds'} "
                    f"${self._max_premium_usd:.0f} limit"
                ),
                weight=0.10,
                bullish=(premium <= self._max_premium_usd),
            ),
        ]

        return evidence

    async def select_contract(
        self, evidence: list[Evidence], raw_data: Any
    ) -> OptionContract | None:
        if raw_data is None:
            return None

        buy: EverestBuySignal = raw_data
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
        # Everest is a human analyst — fixed moderate confidence.
        return 0.70

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

        buy: EverestBuySignal = raw_data
        evidence = await self.build_evidence(buy)
        if not evidence:
            return

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
            confidence=0.70,
            exit_rules=self.exit_rules,
            source_metadata={
                "message_id": buy.message_id,
                "channel_id": buy.channel_id,
                "raw": buy.raw_content[:300],
                "execution_buffer_pct": self._execution_buffer_pct,
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
            signal.symbol, signal.direction, signal.strike,
            signal.expiry, signal.signal_price,
        )

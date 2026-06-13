"""
analysts/discord/pilla_swings.py — Pilla Swing Trades analyst.

Pilla posts swing trade option alerts in a Discord channel.
Exit strategy: OWNER_LAST_SELL — close position 10 minutes after owner's last sell message.

BUY formats:
  "Entering TSLA 430C at 3.50 exp 06/20"
  "Buy AAPL 200C at 2.10"
  "Added NVDA 1200C at 10.50 exp 07/18/2026"
  "Bought SPY 735P at 1.10"
  "Bougth MSFT 455C at 4.80"  (typo variant)

SELL formats (owner posts to signal partial/full exit):
  "Selling some TSLA"
  "Selling all AAPL"
  "Selling most NVDA"
  "Out of SPY"
  "Closed TSLA"

Exit rule: OWNER_LAST_SELL with 600 seconds of silence = declare final exit.
Channel ID is a placeholder until the real channel ID is configured.
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

logger = logging.getLogger("analyst.pilla_swings")

# ─── Channel placeholder ──────────────────────────────────────────────────────

PILLA_CHANNEL_PLACEHOLDER = "PILLA_CHANNEL_PLACEHOLDER"

# ─── Regex patterns ───────────────────────────────────────────────────────────

# BUY pattern — handles:
#   Entering / Buy / Added / Bought / Bougth (typo)
#   SYMBOL  strike  C/P  at/@ price
#   optional: exp/expiry/expires 6/20 or 06/20/26 or 06/20/2026
_PILLA_BUY_RE = re.compile(
    r"(?:Entering|Buy|Added|Bought|Bougth)\s+"
    r"([A-Z]{1,5})\s+"
    r"(\d+(?:\.\d+)?)\s*([CP])\s+"
    r"(?:at|@)\s+"
    r"(\d+(?:\.\d+)?)"
    r"(?:.*?exp(?:iry|ires?)?\s*:?\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?))?",
    re.IGNORECASE | re.DOTALL,
)

# SELL pattern — owner signals intent to exit (partial or full)
#   "Selling some/all/most SYMBOL"
#   "Out of SYMBOL"
#   "Closed SYMBOL"
_PILLA_SELL_RE = re.compile(
    r"(?:"
    r"(?:Selling\s+(?:some|all|most|part(?:ial)?|half|rest|remaining)?\s*(?:[A-Z]{1,5})?)"
    r"|(?:Out\s+of\s+[A-Z]{1,5})"
    r"|(?:Closed\s+[A-Z]{1,5})"
    r")",
    re.IGNORECASE,
)


# ─── Parsed message dataclasses ──────────────────────────────────────────────

@dataclass
class PillaBuySignal:
    symbol: str
    direction: OptionDirection
    strike: float
    price: float
    expiry: date | None       # None = unknown/unspecified
    channel_id: str
    message_id: str
    raw_content: str


@dataclass
class PillaSellSignal:
    raw_content: str
    channel_id: str
    message_id: str


# ─── Pure parser functions (testable without Discord) ────────────────────────

def parse_pilla_buy(msg: dict) -> PillaBuySignal | None:
    """
    Parse a Pilla swing trade buy message.

    Returns a PillaBuySignal if the message matches a known buy format, else None.
    No author restriction is applied — Pilla posts directly (not through a bot).
    """
    content = msg.get("content", "")
    if not content:
        return None

    m = _PILLA_BUY_RE.search(content)
    if not m:
        return None

    symbol = m.group(1).upper().strip()
    strike = float(m.group(2))
    direction_char = m.group(3).upper()
    direction: OptionDirection = "CALL" if direction_char == "C" else "PUT"
    price = float(m.group(4))

    # Parse optional expiry: M/D, MM/DD, MM/DD/YY, MM/DD/YYYY
    expiry: date | None = None
    if m.group(5):
        exp_raw = m.group(5).strip()
        parts = exp_raw.split("/")
        try:
            if len(parts) == 2:
                # MM/DD — assume current year
                month, day = int(parts[0]), int(parts[1])
                year = datetime.now(tz=timezone.utc).year
                expiry = date(year, month, day)
            elif len(parts) == 3:
                month, day = int(parts[0]), int(parts[1])
                yr = parts[2]
                if len(yr) == 2:
                    year = 2000 + int(yr)
                else:
                    year = int(yr)
                expiry = date(year, month, day)
        except (ValueError, TypeError):
            expiry = None  # Malformed date — treat as unknown

    return PillaBuySignal(
        symbol=symbol,
        direction=direction,
        strike=strike,
        price=price,
        expiry=expiry,
        channel_id=msg.get("channel_id", ""),
        message_id=msg.get("message_id", ""),
        raw_content=content,
    )


def is_pilla_sell(msg: dict) -> bool:
    """
    Return True if the message is a Pilla sell/exit signal.

    Used by the Monitor Agent to reset the OWNER_LAST_SELL silence timer.
    No author restriction — caller is responsible for channel filtering.
    """
    content = msg.get("content", "")
    if not content:
        return False
    return bool(_PILLA_SELL_RE.search(content))


def parse_pilla_sell(msg: dict) -> PillaSellSignal | None:
    """
    Parse a Pilla sell message. Returns PillaSellSignal if sell detected, else None.
    """
    if not is_pilla_sell(msg):
        return None
    return PillaSellSignal(
        raw_content=msg.get("content", ""),
        channel_id=msg.get("channel_id", ""),
        message_id=msg.get("message_id", ""),
    )


# ─── PillaSwingsAnalyst ───────────────────────────────────────────────────────

class PillaSwingsAnalyst(BaseAnalyst):
    """
    Listens to Pilla's swing trade Discord channel.
    Emits a TradeSignal for every buy alert.
    Exit: OWNER_LAST_SELL — close 10 minutes after owner's last sell message.

    Channel ID is a placeholder — update configs/analysts/pilla_swings.json
    and pass the real channel_id when instantiating.
    """

    analyst_id = "pilla_swings"

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        channel_id: str = PILLA_CHANNEL_PLACEHOLDER,
        *,
        execution_buffer_pct: float = 0.20,
        max_premium_usd: float = 1000.0,
        confidence_threshold: float = 0.72,
    ) -> None:
        exit_rules = ExitRules(
            strategy="OWNER_LAST_SELL",
            source_channel_id=channel_id,
            owner_silence_seconds=600,
        )
        super().__init__(
            analyst_id=self.__class__.analyst_id,
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
        self._log.info("PillaSwingsAnalyst starting (channel=%s)", self._channel_id)
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
        return parse_pilla_buy(msg)

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        if raw_data is None:
            return []

        buy: PillaBuySignal = raw_data
        premium = buy.price * 100

        evidence = [
            Evidence(
                indicator="pilla_buy_signal",
                value=buy.raw_content[:200],
                interpretation=(
                    f"Pilla entered {buy.symbol} {buy.strike}{buy.direction[0]} "
                    f"at ${buy.price:.2f}"
                ),
                weight=0.85,
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

        if buy.expiry:
            evidence.append(
                Evidence(
                    indicator="expiry_known",
                    value=str(buy.expiry),
                    interpretation=f"Expiry specified: {buy.expiry}",
                    weight=0.05,
                    bullish=True,
                )
            )

        return evidence

    async def select_contract(
        self, evidence: list[Evidence], raw_data: Any
    ) -> OptionContract | None:
        if raw_data is None:
            return None

        buy: PillaBuySignal = raw_data
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
        # Swing trade signals: fixed confidence for consistency
        return 0.75

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

        buy: PillaBuySignal = raw_data
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
            confidence=0.75,
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

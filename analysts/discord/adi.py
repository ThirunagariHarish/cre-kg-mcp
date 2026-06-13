"""
analysts/discord/adi.py — ADI (Aadi) SPX-only premium alerts analyst.

ADI posts SPX options alerts on channel 1495517143599415507.

KNOWN MESSAGE FORMAT (from scraping):
  Author: "Aadi [INFR]" or "INFR [BOT]" (is_bot=True)
  Content: "@here SPX {strike}C at {price}"
           "@here SPX {strike}P at {price}"
           "@here SPX {strike}C/P at {price}"  <- dual direction (take the one with a strike)

  Sell: "@here Sold/Closed/Out SPX {strike}C/P at {price}"
        Same author filter (Aadi/INFR, is_bot=True).

Exit: FIRST_SELL_FROM_SOURCE on channel 1495517143599415507
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NamedTuple

from core.base_analyst import BaseAnalyst, WakeEvent
from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    OptionDirection,
    TradeSignal,
)

logger = logging.getLogger("analyst.adi")

# ─── Channel ──────────────────────────────────────────────────────────────────

_CHANNEL_ID = "1495517143599415507"

# ─── Author filter ────────────────────────────────────────────────────────────

# Buy/sell alerts are posted by the Aadi/INFR bot.
# Username must contain "Aadi" OR "INFR" (case-insensitive) AND is_bot=True.
_AUTHOR_FRAGMENTS = ("aadi", "infr")

# ─── Regex patterns ───────────────────────────────────────────────────────────

# BUY patterns:
# "@here SPX 7400C at 2.50"
# "@here SPX 7400P at 2.50"
# "@here SPX 7400C/P at 2.50"  <- dual — take CALL (left side has the strike)
_ADI_BUY_RE = re.compile(
    r"@here\s+SPX\s+(\d+(?:\.\d+)?)\s*([CP])(?:/[CP])?\s+at\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# SELL patterns:
# "@here Sold SPX 7400C at 5.00"
# "@here Closed SPX 7400P at 3.20"
# "@here Out SPX 7400C at 4.50"
_ADI_SELL_RE = re.compile(
    r"@here\s+(?:Sold|Closed|Out)\s+SPX\s+(\d+(?:\.\d+)?)\s*([CP])\s+at\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# ─── Parsed message types ─────────────────────────────────────────────────────


class BuySignal(NamedTuple):
    symbol: str
    direction: OptionDirection
    strike: float
    price: float
    expiry: None  # ADI messages do not include expiry; caller uses today (0DTE)
    channel_id: str
    message_id: str
    raw_content: str


class SellSignal(NamedTuple):
    symbol: str
    direction: OptionDirection
    strike: float
    price: float


# ─── Author check ─────────────────────────────────────────────────────────────


def _is_adi_author(msg: dict) -> bool:
    """Returns True if the message is from an Aadi/INFR bot."""
    name = (msg.get("author_global_name") or msg.get("author_name") or "").lower()
    return any(frag in name for frag in _AUTHOR_FRAGMENTS) and msg.get("is_bot", False)


# ─── Pure parser functions (testable without Discord) ─────────────────────────


def parse_adi_buy(msg: dict) -> BuySignal | None:
    """
    Parse an ADI buy message. Returns None if the message is not an ADI SPX buy.

    Handles:
      @here SPX 7400C at 2.50
      @here SPX 7400P at 2.50
      @here SPX 7400C/P at 2.50  (dual direction — takes CALL since strike is on C side)
    Only processes SPX. Any other symbol is ignored.
    """
    if not _is_adi_author(msg):
        return None

    content = msg.get("content", "")

    # Ensure the symbol is SPX (regex already hardcodes SPX but guard for clarity)
    m = _ADI_BUY_RE.search(content)
    if not m:
        return None

    strike = float(m.group(1))
    direction: OptionDirection = "CALL" if m.group(2).upper() == "C" else "PUT"
    price = float(m.group(3))

    return BuySignal(
        symbol="SPX",
        direction=direction,
        strike=strike,
        price=price,
        expiry=None,  # SPX 0DTE — caller uses today
        channel_id=msg.get("channel_id", _CHANNEL_ID),
        message_id=msg.get("message_id", ""),
        raw_content=content,
    )


def parse_adi_sell(msg: dict) -> SellSignal | None:
    """
    Parse an ADI sell message. Returns None if not an ADI sell signal.

    Handles:
      @here Sold SPX 7400C at 5.00
      @here Closed SPX 7400P at 3.20
      @here Out SPX 7400C at 4.50
    """
    if not _is_adi_author(msg):
        return None

    content = msg.get("content", "")
    m = _ADI_SELL_RE.search(content)
    if not m:
        return None

    strike = float(m.group(1))
    direction: OptionDirection = "CALL" if m.group(2).upper() == "C" else "PUT"
    price = float(m.group(3))

    return SellSignal(
        symbol="SPX",
        direction=direction,
        strike=strike,
        price=price,
    )


# ─── ADIAnalyst ───────────────────────────────────────────────────────────────


class ADIAnalyst(BaseAnalyst):
    """
    Listens to the ADI premium alerts channel.
    Emits TradeSignal on every SPX buy alert.
    Exit: FIRST_SELL_FROM_SOURCE (100% close on ADI's first sell).

    Only SPX options are traded. All other symbols are silently ignored.
    """

    analyst_id = "adi"
    source_layer = "DISCORD"

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        channel_id: str = _CHANNEL_ID,
        *,
        execution_buffer_pct: float = 0.15,
        max_premium_usd: float = 800.0,
        confidence_threshold: float = 0.75,
    ) -> None:
        exit_rules = ExitRules(
            strategy="FIRST_SELL_FROM_SOURCE",
            source_channel_id=channel_id,
        )
        super().__init__(
            analyst_id="adi",
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
        self._log.info("ADIAnalyst starting on channel %s", self._channel_id)
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
        return parse_adi_buy(msg)

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        if raw_data is None:
            return []

        buy: BuySignal = raw_data
        premium = buy.price * 100

        return [
            Evidence(
                indicator="adi_buy_signal",
                value=buy.raw_content[:200],
                interpretation=f"ADI bought SPX {buy.strike}{buy.direction[0]} at ${buy.price}",
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

    async def select_contract(
        self, evidence: list[Evidence], raw_data: Any
    ) -> OptionContract | None:
        if raw_data is None:
            return None

        buy: BuySignal = raw_data
        premium = buy.price * 100
        if premium > self._max_premium_usd:
            self._log.info(
                "Signal rejected: premium $%.0f > max $%.0f",
                premium,
                self._max_premium_usd,
            )
            return None

        limit_price = round(buy.price * (1 + self._execution_buffer_pct), 2)
        expiry = datetime.now(tz=timezone.utc).date()  # ADI = SPX 0DTE

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
        return 0.80

    def _infer_direction(self, evidence: list[Evidence]) -> OptionDirection:  # type: ignore[override]
        # Unused — ADIAnalyst overrides _process to get direction from BuySignal directly
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

        contract = await self.select_contract(evidence, buy)
        if contract is None:
            return

        dedup_key = f"{self.analyst_id}:{buy.symbol}:{buy.strike}:{buy.direction}"
        if dedup_key in self._seen_signal_keys:
            self._log.info("Duplicate buy suppressed: %s", dedup_key)
            return
        self._seen_signal_keys.add(dedup_key)
        asyncio.create_task(self._clear_dedup(dedup_key, delay=300))

        expiry = datetime.now(tz=timezone.utc).date()
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
            risk_level="HIGH",
            confidence=0.80,
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
            signal.symbol,
            signal.direction,
            signal.strike,
            signal.expiry,
            signal.signal_price,
        )

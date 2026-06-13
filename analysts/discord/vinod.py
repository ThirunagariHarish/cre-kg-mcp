"""
analysts/discord/vinod.py — Vinod SPX and Vinod Other-Trades analysts.

Two analysts, two queues, one source:
  VinodSPXAnalyst  — channel: #spx-es-alerts-vinod
  VinodOtherAnalyst — channel: #other-trades-vinod

Message formats confirmed from scraped samples (2026-06-12):

BUY (author: "INFRA TRADE ALERT [BOT]" / "INFRA [BOT]"):
  SPX channel:   **SPX :** Bought SPX {strike}C/P at {price} {notes}
  Other channel: **OTHER :** Bought {SYMBOL} {strike}C/P at {price} Exp: {MM/DD/YYYY} {notes}
                 **OTHER :** Bought {SYMBOL} {strike}C/P at {price} Expiring today

SELL (author starts with "singhvinod77"):
  @here Sold {X}% {SYMBOL} {strike}C/P at {price}
  @here Sold most {SYMBOL} {strike}C/P at {price}
  @here Sold most runners at {price}
  @here Sold {N} more {SYMBOL} {strike}C/P at {price}
  @here Closed most {SYMBOL} {strike}C/P at {price}
  @here Last {N} {SYMBOL} {strike}C/P at {price}

Exit rules:
  SPX:   first sell → close 100% (FIRST_SELL_FROM_SOURCE)
  Other: first sell → close 70%, second sell → close remaining 30% (PARTIAL_SELL_PCT)
"""

from __future__ import annotations

import asyncio
import logging
import os
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

logger = logging.getLogger("analyst.vinod")

# ─── Authors ──────────────────────────────────────────────────────────────────

# Buys are posted by the INFRA bot. Username contains "INFRA".
_BUY_AUTHOR_FRAGMENT = "INFRA"

# Sells are posted by singhvinod77 bot.
_SELL_AUTHOR_FRAGMENT = "singhvinod77"

# ─── Strategies to ignore ────────────────────────────────────────────────────

_IGNORE_STRATEGY_KEYWORDS = frozenset(
    ["fly", "butterfly", "condor", "iron condor", "iron_condor", "ic", "strangle", "straddle"]
)

# ─── Regex patterns ───────────────────────────────────────────────────────────

# BUY patterns:
# **SPX :** Bought SPX 7550C at 3.50 ...
# **SPX :** Bought SPX 7440P at 4
# Note: Vinod has a consistent typo "Bougth" — both spellings are handled.
_SPX_BUY_RE = re.compile(
    r"\*\*SPX\s*:\*\*\s*Boug(?:ht|th)\s+SPX\s+(\d+(?:\.\d+)?)\s*([CP])\s+at\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# **OTHER :** Bought TSLA 430C at 1.70 Expiring today
# **OTHER :** Bought MSFT 455C at 4.80 Exp: 06/26/2026
# **OTHER :** Bougth AMD 500C at 1.20 Lotto Expiring tomm  (typo)
_OTHER_BUY_RE = re.compile(
    r"\*\*OTHER\s*:\*\*\s*Boug(?:ht|th)\s+([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CP])\s+at\s+(\d+(?:\.\d+)?)"
    r"(?:.*?Exp(?:iring)?\s*:?\s*(today|tomm(?:orrow)?|(\d{1,2}/\d{1,2}/\d{4})))?",
    re.IGNORECASE | re.DOTALL,
)

# SELL patterns:
# @here Sold 50% SPX 7550C at 8.50
# @here Sold most SPX 7550C at 8.50
# @here Closed most SPX 7550C at 8.50
# @here Last 2 SPX 7550C at 8.50
# @here Sold most runners at 8.50  (no ticker/strike — context-dependent)
# @here Sold most 7395P at 2.20  (no ticker — strike only; symbol resolved from context)
# Requires explicit uppercase ticker [A-Z]{2,5} to avoid "MOST" being captured as ticker.
# @here is optional for the structured path — full contract (symbol+strike+C/P+price)
# is specific enough without it. @here IS required for the unstructured fallback path
# (see parse_sell) to prevent stoploss commentary from being parsed as sells.
_SELL_RE = re.compile(
    r"(?:@here\s+)?(?:Sold|Closed|Last)\s+"
    r"(?:(\d+(?:\.\d+)?%?|most|runners?|all)\s+)?"
    r"(?:more\s+)?"
    r"(?:([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s*([CP])\s+(?:at|around)\s+(\d+(?:\.\d+)?)"
    r"|runners?\s+(?:at|around)\s+(\d+(?:\.\d+)?))",
    re.IGNORECASE,
)

# Words that look like tickers but are quantity/direction words — reject if captured as symbol.
_PSEUDO_TICKER_WORDS = frozenset(
    ["MOST", "ALL", "LAST", "MORE", "SOME", "HALF", "REST", "SOLD", "RUNNERS", "RUNNER"]
)

# ─── Parsed message dataclasses ──────────────────────────────────────────────

@dataclass
class BuySignal:
    symbol: str
    direction: OptionDirection
    strike: float
    price: float
    expiry: date | None      # None means same-day (0DTE) or unknown
    channel_id: str
    message_id: str
    raw_content: str


@dataclass
class SellSignal:
    symbol: str | None       # None if "Sold most runners at X"
    direction: OptionDirection | None
    strike: float | None
    price: float
    quantity_hint: str | None  # "50%", "most", "all", "runners", etc.
    channel_id: str
    message_id: str
    raw_content: str


# ─── Pure parser functions (testable without Discord) ────────────────────────

def parse_spx_buy(msg: dict) -> BuySignal | None:
    """
    Parse an SPX buy message. Returns None if the message is not a Vinod SPX buy.
    Rejects futures (ES, /ES) and multi-leg strategies (fly, condor, strangle).
    """
    if not _is_buy_author(msg):
        return None

    content = msg["content"]

    if _is_ignored_strategy(content):
        return None

    m = _SPX_BUY_RE.search(content)
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
        expiry=None,  # SPX messages don't include expiry — caller uses today
        channel_id=msg["channel_id"],
        message_id=msg["message_id"],
        raw_content=content,
    )


def parse_other_buy(msg: dict) -> BuySignal | None:
    """
    Parse an Other-Trades buy message. Returns None if not a Vinod other buy.
    Ignores SPX/ES trades (those belong to the SPX analyst).
    """
    if not _is_buy_author(msg):
        return None

    content = msg["content"]

    if _is_ignored_strategy(content):
        return None

    m = _OTHER_BUY_RE.search(content)
    if not m:
        return None

    symbol = m.group(1).upper()

    # SPX/ES futures belong to the SPX analyst or are not traded.
    # SPY, QQQ, and all other equities belong to the Other analyst.
    if symbol in ("SPX", "ES", "NQ"):
        return None

    strike = float(m.group(2))
    direction: OptionDirection = "CALL" if m.group(3).upper() == "C" else "PUT"
    price = float(m.group(4))

    expiry: date | None = None
    if m.group(5):
        exp_raw = m.group(5).strip().lower()
        today = datetime.now(tz=timezone.utc).date()
        if exp_raw in ("today",):
            expiry = today
        elif exp_raw.startswith("tomm"):  # "tomm" / "tomorrow" typo variants
            from datetime import timedelta
            expiry = today + timedelta(days=1)
        elif m.group(6):
            try:
                expiry = datetime.strptime(m.group(6), "%m/%d/%Y").date()
            except ValueError:
                pass

    return BuySignal(
        symbol=symbol,
        direction=direction,
        strike=strike,
        price=price,
        expiry=expiry,
        channel_id=msg["channel_id"],
        message_id=msg["message_id"],
        raw_content=content,
    )


def parse_sell(msg: dict) -> SellSignal | None:
    """
    Parse a Vinod sell message. Returns None if not a sell signal.
    Works for both SPX and Other channels.

    The @here prefix requirement applies to the unstructured fallback only —
    it prevents false positives on stoploss commentary like "Stoploss at 7310".
    The structured _SELL_RE path (full contract: symbol + strike + direction + price)
    is safe without @here because it requires a complete contract specification.
    """
    if not _is_sell_author(msg):
        return None

    content = msg["content"]

    # Try structured match first — safe without @here (full contract required:
    # symbol + strike + direction + price). This catches "Sold 50% SPX 7415C at 3.50"
    # without @here, which Vinod sometimes omits.
    m = _SELL_RE.search(content)
    if not m:
        # Fallback: unstructured sell — ONLY accept if prefixed with @here to avoid
        # false-positives on stoploss commentary ("Stoploss at 7310").
        if not content.startswith("@here"):
            return None
        price_m = re.search(r"(?:at|around)\s+(\d+(?:\.\d+)?)", content)
        if price_m:
            return SellSignal(
                symbol=None,
                direction=None,
                strike=None,
                price=float(price_m.group(1)),
                quantity_hint="unknown",
                channel_id=msg["channel_id"],
                message_id=msg["message_id"],
                raw_content=content,
            )
        return None

    # Named-ticker sell: @here Sold 50% SPX 7550C at 8.50
    if m.group(2):
        symbol = m.group(2).upper()
        # Reject if "symbol" is a quantity/direction word caught by regex backtracking
        if symbol in _PSEUDO_TICKER_WORDS:
            symbol = None
            strike = None
            direction = None
            # Try to find price after "at/around" in the fallback
            price_m = re.search(r"(?:at|around)\s+(\d+(?:\.\d+)?)", content)
            price = float(price_m.group(1)) if price_m else 0.0
            qty_hint = m.group(1) or "unknown"
        else:
            strike = float(m.group(3))
            direction_char = m.group(4).upper() if m.group(4) else "C"
            direction = "CALL" if direction_char == "C" else "PUT"
            price = float(m.group(5))
            qty_hint = m.group(1) or "all"
    else:
        # "Sold most runners at 8.50" — no specific contract info
        symbol = None
        direction = None
        strike = None
        price = float(m.group(6))
        qty_hint = "runners"

    return SellSignal(
        symbol=symbol,
        direction=direction,
        strike=strike,
        price=price,
        quantity_hint=qty_hint,
        channel_id=msg["channel_id"],
        message_id=msg["message_id"],
        raw_content=content,
    )


# ─── Author checks ────────────────────────────────────────────────────────────

def _is_buy_author(msg: dict) -> bool:
    name = (msg.get("author_global_name") or msg.get("author_name") or "").upper()
    return _BUY_AUTHOR_FRAGMENT in name and msg.get("is_bot", False)


def _is_sell_author(msg: dict) -> bool:
    name = (msg.get("author_global_name") or msg.get("author_name") or "").lower()
    return "singhvinod77" in name and msg.get("is_bot", False)


def _is_ignored_strategy(content: str) -> bool:
    low = content.lower()
    return any(kw in low for kw in _IGNORE_STRATEGY_KEYWORDS)


# ─── VinodSPXAnalyst ──────────────────────────────────────────────────────────

class VinodSPXAnalyst(BaseAnalyst):
    """
    Listens to #spx-es-alerts-vinod. Emits TradeSignal on every buy.
    Exit: FIRST_SELL_FROM_SOURCE (100% close on Vinod's first sell).

    Buffers:
      - entry_buffer_pct (0.30): max acceptable slippage above Vinod's price
      - execution_buffer_pct (0.20): RH limit order price = signal_price × 1.20
    """

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        channel_id: str,
        *,
        entry_buffer_pct: float = 0.30,
        execution_buffer_pct: float = 0.20,
        max_premium_usd: float = 800.0,
        confidence_threshold: float = 0.70,
    ) -> None:
        exit_rules = ExitRules(
            strategy="FIRST_SELL_FROM_SOURCE",
            source_channel_id=channel_id,
        )
        super().__init__(
            analyst_id="vinod_spx",
            source_layer="DISCORD",
            exit_rules=exit_rules,
            signal_queue=signal_queue,
            wake_trigger="DISCORD_MESSAGE",
            min_evidence_items=1,
            confidence_threshold=confidence_threshold,
        )
        self._channel_id = channel_id
        self._entry_buffer_pct = entry_buffer_pct
        self._execution_buffer_pct = execution_buffer_pct
        self._max_premium_usd = max_premium_usd
        self._msg_queue: asyncio.Queue[dict] = asyncio.Queue()

    @property
    def message_queue(self) -> "asyncio.Queue[dict]":
        """The gateway puts Discord messages here."""
        return self._msg_queue

    async def run(self) -> None:
        self._running = True
        self._log.info("VinodSPXAnalyst starting")
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
        buy = parse_spx_buy(msg)
        return buy

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        if raw_data is None:
            return []

        buy: BuySignal = raw_data

        premium = buy.price * 100  # per contract
        premium_pct = min(1.0, premium / self._max_premium_usd) if self._max_premium_usd else 0.5

        return [
            Evidence(
                indicator="vinod_buy_signal",
                value=buy.raw_content[:200],
                interpretation=f"Vinod bought {buy.symbol} {buy.strike}{buy.direction[0]} at ${buy.price}",
                weight=0.90,
                bullish=(buy.direction == "CALL"),
            ),
            Evidence(
                indicator="premium_check",
                value=premium,
                interpretation=f"Premium ${premium:.0f}/contract — {'within' if premium <= self._max_premium_usd else 'exceeds'} ${self._max_premium_usd:.0f} limit",
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

        # Reject if premium exceeds max
        premium = buy.price * 100
        if premium > self._max_premium_usd:
            self._log.info(
                "Signal rejected: premium $%.0f > max $%.0f",
                premium,
                self._max_premium_usd,
            )
            return None

        # Limit price: execution_buffer above Vinod's stated price
        limit_price = round(buy.price * (1 + self._execution_buffer_pct), 2)

        # Use today's date for SPX 0DTE if no expiry provided
        expiry = buy.expiry or datetime.now(tz=timezone.utc).date()

        return OptionContract(
            symbol=buy.symbol,
            direction=buy.direction,
            strike=buy.strike,
            expiry=expiry,
            bid_per_share=buy.price * 0.95,    # estimated — gateway will get real quote
            ask_per_share=limit_price,
            mark_per_share=buy.price,
            open_interest=0,
            volume=0,
        )

    def compute_confidence(self, evidence: list[Evidence]) -> float:
        # For Discord signals we trust Vinod. Fixed high confidence.
        return 0.80

    def _infer_direction(self, evidence: list[Evidence]) -> OptionDirection:  # type: ignore[override]
        # Unused — VinodSPXAnalyst overrides _process to get direction from BuySignal directly
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
            risk_level="HIGH",
            confidence=0.80,
            exit_rules=self.exit_rules,
            source_metadata={
                "message_id": buy.message_id,
                "channel_id": buy.channel_id,
                "raw": buy.raw_content[:300],
                "entry_buffer_pct": self._entry_buffer_pct,
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


# ─── VinodOtherAnalyst ────────────────────────────────────────────────────────

class VinodOtherAnalyst(BaseAnalyst):
    """
    Listens to #other-trades-vinod. Emits TradeSignal on every buy.
    Exit: PARTIAL_SELL_PCT — 70% on first sell, remaining 30% on second sell.
    """

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        channel_id: str,
        *,
        entry_buffer_pct: float = 0.30,
        execution_buffer_pct: float = 0.20,
        max_premium_usd: float = 800.0,
        confidence_threshold: float = 0.70,
    ) -> None:
        exit_rules = ExitRules(
            strategy="PARTIAL_SELL_PCT",
            partial_sell_pct=0.70,
            source_channel_id=channel_id,
        )
        super().__init__(
            analyst_id="vinod_other",
            source_layer="DISCORD",
            exit_rules=exit_rules,
            signal_queue=signal_queue,
            wake_trigger="DISCORD_MESSAGE",
            min_evidence_items=1,
            confidence_threshold=confidence_threshold,
        )
        self._channel_id = channel_id
        self._entry_buffer_pct = entry_buffer_pct
        self._execution_buffer_pct = execution_buffer_pct
        self._max_premium_usd = max_premium_usd
        self._msg_queue: asyncio.Queue[dict] = asyncio.Queue()

    @property
    def message_queue(self) -> "asyncio.Queue[dict]":
        return self._msg_queue

    async def run(self) -> None:
        self._running = True
        self._log.info("VinodOtherAnalyst starting")
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

    async def gather_data(self, trigger: WakeEvent) -> Any:
        msg = trigger.raw
        if not isinstance(msg, dict):
            return None
        return parse_other_buy(msg)

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        if raw_data is None:
            return []

        buy: BuySignal = raw_data
        premium = buy.price * 100

        evidence = [
            Evidence(
                indicator="vinod_other_signal",
                value=buy.raw_content[:200],
                interpretation=f"Vinod bought {buy.symbol} {buy.strike}{buy.direction[0]} at ${buy.price}",
                weight=0.85,
                bullish=(buy.direction == "CALL"),
            ),
            Evidence(
                indicator="premium_check",
                value=premium,
                interpretation=f"Premium ${premium:.0f}/contract",
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

        buy: BuySignal = raw_data
        premium = buy.price * 100
        if premium > self._max_premium_usd:
            self._log.info("Rejected: premium $%.0f > max $%.0f", premium, self._max_premium_usd)
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
        return 0.78

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
            confidence=0.78,
            exit_rules=self.exit_rules,
            source_metadata={
                "message_id": buy.message_id,
                "channel_id": buy.channel_id,
                "raw": buy.raw_content[:300],
            },
        )

        await self.signal_queue.put(signal)
        from core.logging import TradeEvent, journal
        journal(
            TradeEvent.SIGNAL_EMITTED,
            self.analyst_id,
            signal.signal_id,
            extra={
                "symbol": signal.symbol,
                "direction": signal.direction,
                "strike": signal.strike,
                "expiry": str(signal.expiry),
            },
        )
        self._log.info(
            "Signal emitted: %s %s %.0f exp=%s @ $%.2f",
            signal.symbol, signal.direction, signal.strike,
            signal.expiry, signal.signal_price,
        )

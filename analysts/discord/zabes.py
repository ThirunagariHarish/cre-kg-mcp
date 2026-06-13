"""
analysts/discord/zabes.py — ZabesAnalyst: multi-line swing trade Discord analyst.

Also known as Waxui/ZAPs. Listens to channel 1495516822349414430.

KNOWN MESSAGE FORMATS (from scraping):

Format 1 (HIGH RISK swing, multi-line):
  @here **HIGH RISK**
  SPY here
  06/15 735P
  Avg. 1.50

Format 2 (standard swing, multi-line):
  @here SPY here
  06/20 740C
  Avg. 1.80

Format 3 (direct single-line):
  @here SPX 7400P at 2.50 exp 6/20

Exit: OWNER_FIRST_SELL — close 100% when Zabes posts a sell message.
The monitor watches the same channel (1495516822349414430) for sell keywords.
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

logger = logging.getLogger("analyst.zabes")

# ─── Channel ──────────────────────────────────────────────────────────────────

ZABES_CHANNEL_ID = "1495516822349414430"

# ─── Regex patterns ───────────────────────────────────────────────────────────

# Format 1 & 2: multi-line with "Avg." price indicator
# Matches messages like:
#   @here **HIGH RISK**\nSPY here\n06/15 735P\nAvg. 1.50
#   @here SPY here\n06/20 740C\nAvg. 1.80
_ZABES_BUY_RE = re.compile(
    r"@here.*?(?:HIGH\s+RISK\s*)?"          # optional @here HIGH RISK header
    r"(?:SPY|SPX|QQQ|IWM)\s+here.*?"        # underlying + "here"
    r"(\d{1,2}/\d{1,2})\s+(\d+(?:\.\d+)?)\s*([CP]).*?"  # date + strike + direction
    r"Avg\.\s+(\d+(?:\.\d+)?)",              # average price
    re.IGNORECASE | re.DOTALL,
)

# Format 3: direct single-line
# Matches: @here SPX 7400P at 2.50 exp 6/20
#          @here SPY 735P at 1.50 exp 06/15
_ZABES_DIRECT_RE = re.compile(
    r"@here\s+(?:SPY|SPX|QQQ|IWM)\s+(\d+(?:\.\d+)?)\s*([CP])\s+"
    r"(?:at|@)\s+(\d+(?:\.\d+)?)"           # price
    r"(?:.*?exp(?:iry)?\s+(\d{1,2}/\d{1,2}))?",  # optional expiry
    re.IGNORECASE,
)

# Sell detection keywords
_SELL_KEYWORDS_RE = re.compile(
    r"\b(?:sold|closed|out|sell|selling|exit|exiting)\b",
    re.IGNORECASE,
)


# ─── Parsed message dataclass ─────────────────────────────────────────────────

@dataclass
class ZabesBuySignal:
    symbol: str
    direction: OptionDirection
    strike: float
    price: float
    expiry: date
    channel_id: str
    message_id: str
    raw_content: str
    is_high_risk: bool = False


# ─── Date parsing ─────────────────────────────────────────────────────────────

def _parse_expiry(date_str: str) -> date:
    """
    Parse MM/DD into a date, using the current year.
    If the parsed month is before the current month, roll to next year
    (swing trades are forward-looking).
    """
    today = datetime.now(tz=timezone.utc).date()
    parts = date_str.strip().split("/")
    month = int(parts[0])
    day = int(parts[1])

    year = today.year
    candidate = date(year, month, day)
    if candidate < today:
        # Expiry already passed — assume next year
        candidate = date(year + 1, month, day)
    return candidate


# ─── Pure parser functions (testable without Discord) ────────────────────────

def parse_zabes_buy(msg: dict) -> ZabesBuySignal | None:
    """
    Parse a Zabes buy message. Returns None if the message is not a buy signal.

    Handles three formats:
    1. Multi-line with @here + HIGH RISK header + "SPY here" + date/strike + Avg.
    2. Multi-line with @here + "SPY here" + date/strike + Avg.
    3. Direct single-line: @here SPX 7400P at 2.50 exp 6/20
    """
    content = msg.get("content", "")
    channel_id = msg.get("channel_id", "")
    message_id = msg.get("message_id", "")

    if not content.startswith("@here"):
        return None

    # Detect HIGH RISK flag
    is_high_risk = bool(re.search(r"HIGH\s+RISK", content, re.IGNORECASE))

    # Try Format 1 & 2 first (multi-line with Avg.)
    m = _ZABES_BUY_RE.search(content)
    if m:
        date_str = m.group(1)
        strike = float(m.group(2))
        direction: OptionDirection = "CALL" if m.group(3).upper() == "C" else "PUT"
        price = float(m.group(4))

        # Determine symbol from content
        sym_match = re.search(r"\b(SPY|SPX|QQQ|IWM)\b", content, re.IGNORECASE)
        symbol = sym_match.group(1).upper() if sym_match else "SPY"

        try:
            expiry = _parse_expiry(date_str)
        except (ValueError, IndexError):
            logger.warning("Failed to parse date '%s' in Zabes message", date_str)
            return None

        return ZabesBuySignal(
            symbol=symbol,
            direction=direction,
            strike=strike,
            price=price,
            expiry=expiry,
            channel_id=channel_id,
            message_id=message_id,
            raw_content=content,
            is_high_risk=is_high_risk,
        )

    # Try Format 3 (direct single-line)
    m2 = _ZABES_DIRECT_RE.search(content)
    if m2:
        strike = float(m2.group(1))
        direction = "CALL" if m2.group(2).upper() == "C" else "PUT"
        price = float(m2.group(3))

        sym_match = re.search(r"@here\s+(SPY|SPX|QQQ|IWM)", content, re.IGNORECASE)
        symbol = sym_match.group(1).upper() if sym_match else "SPY"

        date_str = m2.group(4)
        if date_str:
            try:
                expiry = _parse_expiry(date_str)
            except (ValueError, IndexError):
                logger.warning("Failed to parse expiry '%s' in Zabes direct message", date_str)
                return None
        else:
            # No expiry in the message — default to 7 days out for swing trades
            from datetime import timedelta
            expiry = datetime.now(tz=timezone.utc).date() + timedelta(days=7)

        return ZabesBuySignal(
            symbol=symbol,
            direction=direction,
            strike=strike,
            price=price,
            expiry=expiry,
            channel_id=channel_id,
            message_id=message_id,
            raw_content=content,
            is_high_risk=is_high_risk,
        )

    return None


def parse_zabes_sell(msg: dict) -> bool:
    """
    Check if a message from the Zabes channel looks like a sell/exit signal.

    Returns True if Zabes is signaling to close the position.
    The monitor agent uses this to close all open Zabes positions (OWNER_FIRST_SELL).

    Detects keywords: Sold, Closed, Out, sell, selling, exit, exiting
    """
    content = msg.get("content", "")
    return bool(_SELL_KEYWORDS_RE.search(content))


# ─── ZabesAnalyst ─────────────────────────────────────────────────────────────

class ZabesAnalyst(BaseAnalyst):
    """
    Listens to Zabes' swing trade channel (1495516822349414430).
    Emits TradeSignal on every buy alert.

    Exit: OWNER_FIRST_SELL — close 100% when Zabes posts the first sell message.

    Risk levels:
      - HIGH RISK messages → risk_level="HIGH", confidence=0.65
      - Standard messages  → risk_level="MEDIUM", confidence=0.75
    """

    analyst_id = "zabes"
    source_layer = "DISCORD"

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        channel_id: str = ZABES_CHANNEL_ID,
        *,
        execution_buffer_pct: float = 0.20,
        max_premium_usd: float = 600.0,
        confidence_threshold: float = 0.60,
    ) -> None:
        exit_rules = ExitRules(
            strategy="OWNER_FIRST_SELL",
            source_channel_id=channel_id,
        )
        super().__init__(
            analyst_id=self.analyst_id,
            source_layer=self.source_layer,
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
        self._log.info("ZabesAnalyst starting (channel=%s)", self._channel_id)
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
        return parse_zabes_buy(msg)

    async def build_evidence(self, raw_data: Any) -> list[Evidence]:
        if raw_data is None:
            return []

        buy: ZabesBuySignal = raw_data
        premium = buy.price * 100

        evidence = [
            Evidence(
                indicator="zabes_buy_signal",
                value=buy.raw_content[:200],
                interpretation=(
                    f"Zabes {'HIGH RISK ' if buy.is_high_risk else ''}swing: "
                    f"{buy.symbol} {buy.strike}{buy.direction[0]} "
                    f"exp {buy.expiry} @ ${buy.price}"
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
            Evidence(
                indicator="expiry_check",
                value=str(buy.expiry),
                interpretation=f"Swing expiry: {buy.expiry}",
                weight=0.05,
                bullish=True,
            ),
        ]

        return evidence

    async def select_contract(
        self,
        evidence: list[Evidence],
        raw_data: Any,
    ) -> OptionContract | None:
        if raw_data is None:
            return None

        buy: ZabesBuySignal = raw_data
        premium = buy.price * 100

        if premium > self._max_premium_usd:
            self._log.info(
                "Signal rejected: premium $%.0f > max $%.0f",
                premium,
                self._max_premium_usd,
            )
            return None

        limit_price = round(buy.price * (1 + self._execution_buffer_pct), 2)

        return OptionContract(
            symbol=buy.symbol,
            direction=buy.direction,
            strike=buy.strike,
            expiry=buy.expiry,
            bid_per_share=buy.price * 0.95,    # estimated — gateway gets real quote
            ask_per_share=limit_price,
            mark_per_share=buy.price,
            open_interest=0,
            volume=0,
        )

    def compute_confidence(self, evidence: list[Evidence]) -> float:
        # Check if any evidence item indicates HIGH RISK
        for e in evidence:
            if e.indicator == "zabes_buy_signal" and "HIGH RISK" in e.interpretation:
                return 0.65
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

        buy: ZabesBuySignal = raw_data
        evidence = await self.build_evidence(buy)
        if not evidence:
            return

        contract = await self.select_contract(evidence, buy)
        if contract is None:
            return

        dedup_key = f"{self.analyst_id}:{buy.symbol}:{buy.strike}:{buy.direction}:{buy.expiry}"
        if dedup_key in self._seen_signal_keys:
            self._log.info("Duplicate swing suppressed: %s", dedup_key)
            return
        self._seen_signal_keys.add(dedup_key)
        asyncio.create_task(self._clear_dedup(dedup_key, delay=3600))  # 1h for swings

        confidence = self.compute_confidence(evidence)
        risk_level = "HIGH" if buy.is_high_risk else "MEDIUM"

        signal = TradeSignal(
            analyst_id=self.analyst_id,
            source_layer=self.source_layer,
            timestamp=datetime.now(tz=timezone.utc),
            symbol=buy.symbol,
            direction=buy.direction,
            strike=buy.strike,
            expiry=buy.expiry,
            signal_price=buy.price,
            evidence=evidence,
            risk_level=risk_level,
            confidence=confidence,
            exit_rules=self.exit_rules,
            source_metadata={
                "message_id": buy.message_id,
                "channel_id": buy.channel_id,
                "raw": buy.raw_content[:300],
                "is_high_risk": buy.is_high_risk,
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
                "is_high_risk": buy.is_high_risk,
            },
        )
        self._log.info(
            "Signal emitted: %s %s %.1f exp=%s @ $%.2f (conf=%.2f%s)",
            signal.symbol, signal.direction, signal.strike,
            signal.expiry, signal.signal_price, signal.confidence,
            " HIGH_RISK" if buy.is_high_risk else "",
        )

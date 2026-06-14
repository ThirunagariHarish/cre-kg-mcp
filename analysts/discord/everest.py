"""
analysts/discord/everest.py — Everest analyst: option BUY alerts from optionsbuftett.

Monitors the Everest Discord channel where the trader `optionsbuftett` posts
near-term option plays. Only BUY entries are parsed; exits, profit announcements,
and promotional spam are silently dropped.

BUY FORMAT (actual channel format, multi-line message):
  HIGH CONFIDENCE 🎯
  6/12 $MCD 290c @.19
  1000  CONTRACTS

  SUPER HIGH CONFIDENCE 🚨
  6/12 $PG 152.5c @.22
  1000  CONTRACTS

  $100,000 TRADE ALERT 🔥
  6/12 $PG 152.5c @.09
  ADDED SUPER HEAVYYY

Core signal line format:
  {M/D} ${TICKER} {STRIKE}{c/p} @{price}
  e.g. "6/12 $MCD 290c @.19"  →  MCD 290-strike CALL entry=$0.19 expiry=Jun 12

The M/D date in the signal IS the option expiry date (usually same-day / next-day).

IGNORED messages:
  - Exits / profit: "SOLD", "+1,000% 🔥", "LEFT RUNNERS"
  - Ad spam:        "whop.com", "FINAL NOTICE", "FINAL WARNING",
                    "SHUTTING DOWN", "LIFETIME ACCESS", "FREE ALERTS"

Author filter: any author accepted — the content pattern is the gate.
Exit strategy: MANUAL — user closes position via dashboard.
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

# ─── Regex patterns ───────────────────────────────────────────────────────────

# Core signal line: "6/12 $MCD 290c @.19"
#   Group 1: expiry date (M/D or M/DD), e.g. "6/12"
#   Group 2: ticker symbol (without $), e.g. "MCD"
#   Group 3: strike price, e.g. "290" or "152.5"
#   Group 4: direction letter, "c" or "p"
#   Group 5: entry price (digits after @), e.g. ".19" or "2.50"
_SIGNAL_RE = re.compile(
    r"(\d{1,2}/\d{1,2})"            # expiry date M/D
    r"\s+\$([A-Z]{1,5})"            # $TICKER
    r"\s+(\d+(?:\.\d+)?)"           # strike (e.g. 290 or 152.5)
    r"\s*([cpCP])"                  # direction: c/C or p/P (touches strike or spaced)
    r"\s+@(\d*\.?\d+)",             # @price (e.g. @.19 or @2.50)
    re.IGNORECASE,
)

# Optional: contract count line (e.g. "1000  CONTRACTS")
_CONTRACTS_RE = re.compile(
    r"(\d[\d,]*)\s+CONTRACTS",
    re.IGNORECASE,
)

# Confidence label regexes (checked in priority order)
_SUPER_HIGH_RE   = re.compile(r"SUPER\s+HIGH\s+CONFIDENCE", re.IGNORECASE)
_HIGH_RE         = re.compile(r"HIGH\s+CONFIDENCE", re.IGNORECASE)
_TRADE_ALERT_RE  = re.compile(r"\$[\d,]+\s+TRADE\s+ALERT", re.IGNORECASE)  # "$100,000 TRADE ALERT"
_ADDED_RE        = re.compile(r"\bADDED\b", re.IGNORECASE)

# Fast-reject: any match → not a buy entry
_REJECT_RE = re.compile(
    r"\bSOLD\b"                         # exit / profit booking
    r"|LEFT\s+RUNNERS"                  # partial exit announcement
    r"|\+[\d,]+%"                       # gain announcement e.g. "+1,000%"
    r"|whop\.com"                       # promotional spam URL
    r"|FINAL\s+(?:NOTICE|WARNING)"      # ad spam
    r"|SHUTTING\s+DOWN"                 # ad spam
    r"|LIFETIME\s+ACCESS"               # ad spam
    r"|FREE\s+ALERTS?\s+ARE"            # "Free alerts are PERMANENTLY SHUTTING DOWN"
    r"|LOCK\s+IN\s+\$\d",              # "lock in $600 LIFETIME ACCESS"
    re.IGNORECASE,
)


# ─── Parsed message dataclass ─────────────────────────────────────────────────

@dataclass
class EverestBuySignal:
    symbol: str
    direction: OptionDirection
    strike: float
    price: float
    expiry: date | None          # parsed from M/D date in signal; None only on parse failure
    channel_id: str
    message_id: str
    raw_content: str
    confidence: float = 0.70     # dynamic: based on label detected in message
    contracts: int | None = None # number of contracts stated (informational only)
    label: str = "UNKNOWN"       # SUPER_HIGH / HIGH / TRADE_ALERT / ADDED / UNKNOWN


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_expiry(raw_date: str) -> date | None:
    """
    Parse "M/D" or "M/DD" into a date using the current calendar year.
    Returns None only if the string is malformed (should not happen after regex match).
    """
    today = datetime.now(tz=timezone.utc).date()
    try:
        return datetime.strptime(f"{raw_date}/{today.year}", "%m/%d/%Y").date()
    except ValueError:
        return None


def _detect_label(content: str) -> tuple[str, float]:
    """
    Detect the confidence label from the message text.

    Returns (label, confidence) where confidence is:
      SUPER_HIGH   → 0.82   ("SUPER HIGH CONFIDENCE 🚨")
      HIGH         → 0.74   ("HIGH CONFIDENCE 🎯")
      TRADE_ALERT  → 0.76   ("$100,000 TRADE ALERT 🔥")
      ADDED        → 0.68   ("ADDED HEAVY" / "ADDED SUPER HEAVYYY")
      UNKNOWN      → 0.65   (signal found but no confidence header)
    """
    if _SUPER_HIGH_RE.search(content):
        return "SUPER_HIGH", 0.82
    if _HIGH_RE.search(content):
        return "HIGH", 0.74
    if _TRADE_ALERT_RE.search(content):
        return "TRADE_ALERT", 0.76
    if _ADDED_RE.search(content):
        return "ADDED", 0.68
    return "UNKNOWN", 0.65


# ─── Pure parser (testable without Discord) ───────────────────────────────────

def parse_everest_buy(msg: dict) -> EverestBuySignal | None:
    """
    Parse an Everest channel message and return an EverestBuySignal if it is
    an option BUY entry. Returns None for exits, profit announcements, spam,
    and any message that does not contain the signal line pattern.

    Expected buy format (multi-line Discord message):
        HIGH CONFIDENCE 🎯
        6/12 $MCD 290c @.19
        1000  CONTRACTS

    Signal line grammar:
        M/D $TICKER STRIKE{c|p} @PRICE
    """
    content = msg.get("content", "")
    if not content:
        return None

    # Step 1: fast-reject known non-buy patterns
    if _REJECT_RE.search(content):
        return None

    # Step 2: match the core signal line
    m = _SIGNAL_RE.search(content)
    if not m:
        return None

    raw_date  = m.group(1)                       # "6/12"
    symbol    = m.group(2).upper()               # "MCD"
    strike    = float(m.group(3))                # 290.0
    direction: OptionDirection = (
        "CALL" if m.group(4).upper() == "C" else "PUT"
    )
    price = float(m.group(5))                    # 0.19

    # Step 3: parse expiry from the date in the signal line
    expiry = _parse_expiry(raw_date)

    # Step 4: optional contract count
    contracts: int | None = None
    cm = _CONTRACTS_RE.search(content)
    if cm:
        try:
            contracts = int(cm.group(1).replace(",", ""))
        except ValueError:
            pass

    # Step 5: detect label & dynamic confidence
    label, confidence = _detect_label(content)

    return EverestBuySignal(
        symbol=symbol,
        direction=direction,
        strike=strike,
        price=price,
        expiry=expiry,
        channel_id=msg.get("channel_id", ""),
        message_id=msg.get("message_id", ""),
        raw_content=content,
        confidence=confidence,
        contracts=contracts,
        label=label,
    )


# ─── EverestAnalyst ───────────────────────────────────────────────────────────

class EverestAnalyst(BaseAnalyst):
    """
    Listens to the Everest Discord channel. Emits a TradeSignal for every
    option BUY entry posted by optionsbuftett. Exit strategy: MANUAL — user
    closes position via dashboard. No auto-close ever fires.

    Confidence is dynamic (0.65–0.82) based on the label in the message:
      SUPER HIGH CONFIDENCE → 0.82
      $X TRADE ALERT        → 0.76
      HIGH CONFIDENCE       → 0.74
      ADDED [HEAVY]         → 0.68  (position addition; may be an average-down)
      (no label)            → 0.65
    """

    analyst_id = "everest"
    source_layer = "DISCORD"
    exit_rules = ExitRules(strategy="MANUAL")
    confidence_threshold = 0.60   # accept all labels including ADDED

    def __init__(
        self,
        signal_queue: "asyncio.Queue[TradeSignal]",
        channel_id: str,
        *,
        execution_buffer_pct: float = 0.20,
        max_premium_usd: float = 800.0,
        confidence_threshold: float = 0.60,
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
        self._last_confidence: float = 0.65   # updated per-message in _process

    @property
    def message_queue(self) -> "asyncio.Queue[dict]":
        """The Discord gateway puts raw message dicts here."""
        return self._msg_queue

    async def run(self) -> None:
        self._running = True
        self._log.info("EverestAnalyst starting — channel=%s", self._channel_id)
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

        return [
            Evidence(
                indicator="everest_buy_signal",
                value=buy.raw_content[:200],
                interpretation=(
                    f"Everest [{buy.label}]: {buy.symbol} "
                    f"{buy.strike}{buy.direction[0]} @ ${buy.price:.2f}"
                    + (f" × {buy.contracts:,} contracts" if buy.contracts else "")
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
                    f"${self._max_premium_usd:.0f} max"
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
        """Return the dynamic confidence cached from the last parsed signal."""
        return self._last_confidence

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
        self._last_confidence = buy.confidence   # cache for compute_confidence

        evidence = await self.build_evidence(buy)
        if not evidence:
            return

        contract = await self.select_contract(evidence, buy)
        if contract is None:
            return

        # Dedup within 5-minute window: same symbol + strike + direction
        dedup_key = f"{self.analyst_id}:{buy.symbol}:{buy.strike}:{buy.direction}"
        if dedup_key in self._seen_signal_keys:
            self._log.info("Duplicate suppressed: %s", dedup_key)
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
            confidence=buy.confidence,
            exit_rules=self.exit_rules,
            source_metadata={
                "message_id":           buy.message_id,
                "channel_id":           buy.channel_id,
                "label":                buy.label,
                "contracts":            buy.contracts,
                "raw":                  buy.raw_content[:300],
                "execution_buffer_pct": self._execution_buffer_pct,
            },
        )

        await self.signal_queue.put(signal)
        journal(
            TradeEvent.SIGNAL_EMITTED,
            self.analyst_id,
            signal.signal_id,
            extra={
                "symbol":     signal.symbol,
                "direction":  signal.direction,
                "strike":     signal.strike,
                "expiry":     str(signal.expiry),
                "confidence": signal.confidence,
                "label":      buy.label,
            },
        )
        self._log.info(
            "Signal emitted: [%s] %s %s %.1f exp=%s @ $%.2f",
            buy.label,
            signal.symbol,
            signal.direction,
            signal.strike,
            signal.expiry,
            signal.signal_price,
        )

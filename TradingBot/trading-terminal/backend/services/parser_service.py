"""
Parser service — converts raw messages into structured ParsedTradeIdea events.
Uses regex patterns + optional NLP for symbol and direction extraction.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..domain.models import OrderSide, AssetClass, Signal, SignalSource, SignalStrength, now_utc
from ..domain.events import RawMessageReceived, ParsedTradeIdea
from ..ports.outbound import ISignalRepository, IMessageBusPublisher
from ..adapters.kafka_publisher import KafkaTopics

logger = logging.getLogger(__name__)


# Regex patterns
TICKER_RE = re.compile(r"\$([A-Z]{1,5})|(?<!\w)([A-Z]{2,5})(?!\w)")
PRICE_RE = re.compile(r"(?:@|entry|at|price)?\s*\$?\s*(\d{1,6}(?:\.\d{1,4})?)")
STOP_RE = re.compile(r"(?:stop|sl|stop.?loss)\s*:?\s*\$?\s*(\d{1,6}(?:\.\d{1,4})?)", re.IGNORECASE)
TARGET_RE = re.compile(r"(?:target|tp|take.?profit|pt)\s*:?\s*\$?\s*(\d{1,6}(?:\.\d{1,4})?)", re.IGNORECASE)
TIMEFRAME_RE = re.compile(r"\b(\d+[mhdwM]|intraday|swing|scalp|weekly|daily)\b", re.IGNORECASE)

BUY_SIGNALS = {"buy", "long", "bull", "calls", "call", "entry", "buying", "accumulate", "add"}
SELL_SIGNALS = {"sell", "short", "bear", "puts", "put", "exit", "selling", "dump", "fade"}

# Common non-ticker uppercase words to ignore
IGNORE_WORDS = {
    "THE", "AND", "FOR", "NOT", "BUT", "YOU", "ALL", "ARE", "FROM", "HAS",
    "ITS", "CEO", "CFO", "CTO", "IPO", "ETF", "ATH", "ATM", "OTM", "ITM",
    "EPS", "DXY", "GDP", "CPI", "FED", "SEC", "NYSE", "NASDAQ", "FOMC",
}

# Fast-path regex patterns for common signal formats
_PATTERN_FULL = re.compile(
    r"(?P<side>BUY|SELL|LONG|SHORT)\s+\$?(?P<sym>[A-Z]{1,5})"
    r"(?:\s+@\s*\$?(?P<entry>[\d.]+))?"
    r"(?:\s+(?:target|tp|pt)\s*\$?(?P<target>[\d.]+))?"
    r"(?:\s+(?:stop|sl)\s*\$?(?P<stop>[\d.]+))?",
    re.IGNORECASE,
)
_PATTERN_DOLLAR = re.compile(
    r"\$(?P<sym>[A-Z]{1,5})\s+(?P<side>BUY|SELL|LONG|SHORT)\s*(?P<entry>[\d.]+)?",
    re.IGNORECASE,
)
_PATTERN_SIMPLE = re.compile(
    r"(?P<sym>[A-Z]{1,5})\s+(?P<side>long|short|buy|sell)\s*(?P<entry>[\d.]+)?",
    re.IGNORECASE,
)


def extract_ticker(text: str) -> str | None:
    """Extract the most likely ticker symbol from text."""
    dollar_tickers = re.findall(r"\$([A-Z]{1,5})", text.upper())
    if dollar_tickers:
        return dollar_tickers[0]
    matches = re.findall(r"(?<!\w)([A-Z]{2,5})(?!\w)", text.upper())
    for m in matches:
        if m not in IGNORE_WORDS and len(m) >= 2:
            return m
    return None


def extract_direction(text: str) -> OrderSide:
    """Determine trade direction from message text."""
    lower = text.lower()
    words = set(re.findall(r"\b\w+\b", lower))
    buy_score = len(words & BUY_SIGNALS)
    sell_score = len(words & SELL_SIGNALS)
    if sell_score > buy_score:
        return OrderSide.SELL
    return OrderSide.BUY


def extract_price(text: str, pattern: re.Pattern) -> float | None:
    """Extract a price value using the given pattern."""
    match = pattern.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def extract_timeframe(text: str) -> str | None:
    """Extract trading timeframe from text."""
    match = TIMEFRAME_RE.search(text)
    return match.group(1).lower() if match else None


def compute_confidence(text: str, ticker: str | None, entry: float | None) -> float:
    """Heuristic confidence score 0-1 based on signal quality."""
    score = 0.3
    if ticker:
        score += 0.2
    if "$" in text:
        score += 0.1
    if entry:
        score += 0.15
    if extract_price(text, STOP_RE):
        score += 0.1
    if extract_price(text, TARGET_RE):
        score += 0.1
    word_count = len(text.split())
    if word_count >= 10:
        score += 0.05
    return min(1.0, round(score, 2))


class ParserService:
    """
    Parses raw messages into structured trade ideas.
    Consumes from raw-messages topic, produces to parsed-ideas topic.
    Supports regex fast-path and Claude LLM fallback.
    """

    def __init__(
        self,
        signal_repo: ISignalRepository,
        publisher: IMessageBusPublisher,
        ai_adapter: Any = None,
    ) -> None:
        self._repo = signal_repo
        self._publisher = publisher
        self._ai_adapter = ai_adapter
        self._parsed_count = 0
        self._failed_count = 0

    def _regex_parse(self, text: str) -> dict[str, Any] | None:
        """
        Try regex fast-path patterns.
        Returns {symbol, direction, entry, stop, target} or None.
        """
        # Pattern 1: "BUY AAPL @ 185 target 190 stop 182"
        m = _PATTERN_FULL.search(text)
        if m:
            side_str = (m.group("side") or "buy").lower()
            direction = OrderSide.SELL if side_str in ("sell", "short") else OrderSide.BUY
            sym = m.group("sym")
            if sym and sym.upper() not in IGNORE_WORDS:
                return {
                    "symbol": sym.upper(),
                    "direction": direction,
                    "entry": float(m.group("entry")) if m.group("entry") else None,
                    "stop": float(m.group("stop")) if m.group("stop") else None,
                    "target": float(m.group("target")) if m.group("target") else None,
                }

        # Pattern 2: "$AAPL BUY 185"
        m = _PATTERN_DOLLAR.search(text)
        if m:
            side_str = (m.group("side") or "buy").lower()
            direction = OrderSide.SELL if side_str in ("sell", "short") else OrderSide.BUY
            sym = m.group("sym")
            if sym and sym.upper() not in IGNORE_WORDS:
                return {
                    "symbol": sym.upper(),
                    "direction": direction,
                    "entry": float(m.group("entry")) if m.group("entry") else None,
                    "stop": None,
                    "target": None,
                }

        # Pattern 3: "AAPL long 185"
        m = _PATTERN_SIMPLE.search(text)
        if m:
            side_str = (m.group("side") or "buy").lower()
            direction = OrderSide.SELL if side_str in ("sell", "short") else OrderSide.BUY
            sym = m.group("sym")
            if sym and sym.upper() not in IGNORE_WORDS:
                return {
                    "symbol": sym.upper(),
                    "direction": direction,
                    "entry": float(m.group("entry")) if m.group("entry") else None,
                    "stop": None,
                    "target": None,
                }

        return None

    async def _llm_parse(self, text: str) -> dict[str, Any]:
        """Call Claude to extract signal fields. Non-fatal if AI unavailable."""
        if not self._ai_adapter:
            return {"confidence": 0.3, "symbol": None, "direction": "buy", "entry": None, "stop": None, "target": None}

        prompt = f"""Extract trading signal information from this text. Return ONLY valid JSON with these exact fields:
{{
  "symbol": "TICKER or null",
  "direction": "buy or sell",
  "entry": null or price as number,
  "stop": null or price as number,
  "target": null or price as number,
  "confidence": 0.0 to 1.0
}}

Text: {text[:500]}"""

        try:
            raw = await self._ai_adapter.analyze(prompt, {})
            raw = raw.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            data = json.loads(raw)
            return data
        except Exception as exc:
            logger.warning("LLM parse failed (non-fatal): %s", exc)
            return {"confidence": 0.3, "symbol": None, "direction": "buy", "entry": None, "stop": None, "target": None}

    async def parse_signal(self, signal: Signal) -> Signal:
        """
        Parse a Signal object — try regex fast-path, fall back to LLM.
        Updates signal fields and saves to DB.
        """
        text = signal.raw_message

        # 1. Try regex fast-path
        parsed = self._regex_parse(text)

        # 2. If regex fails, use Claude LLM
        if not parsed:
            parsed = await self._llm_parse(text)

        if parsed:
            if parsed.get("symbol") and parsed["symbol"] not in IGNORE_WORDS:
                signal.symbol = parsed["symbol"]
            if parsed.get("direction"):
                d = str(parsed["direction"]).lower()
                signal.direction = OrderSide.SELL if d in ("sell", "short") else OrderSide.BUY
            if parsed.get("entry"):
                signal.suggested_entry = float(parsed["entry"])
            if parsed.get("stop"):
                signal.suggested_stop = float(parsed["stop"])
            if parsed.get("target"):
                signal.suggested_target = float(parsed["target"])
            if parsed.get("confidence"):
                signal.confidence = min(1.0, max(0.0, float(parsed["confidence"])))

        # Recompute confidence if we still have low score
        signal.parsed_text = text[:500]

        # Save updated signal
        try:
            await self._repo.save_signal(signal)
        except Exception as e:
            logger.warning("Failed to save parsed signal: %s", e)

        return signal

    async def parse_message(
        self,
        raw_message_id: str,
        source: str,
        content: str,
        metadata: dict | None = None,
    ) -> Signal | None:
        """
        Parse a raw message into a Signal domain object.
        Returns None if the message cannot be parsed into a trade idea.
        """
        metadata = metadata or {}
        ticker = extract_ticker(content)

        if not ticker:
            logger.debug("No ticker found in message: %.80s", content)
            self._failed_count += 1
            return None

        direction = extract_direction(content)
        entry_price = extract_price(content, PRICE_RE)
        stop_price = extract_price(content, STOP_RE)
        target_price = extract_price(content, TARGET_RE)
        timeframe = extract_timeframe(content)
        confidence = compute_confidence(content, ticker, entry_price)

        source_map = {
            "discord": SignalSource.DISCORD,
            "news": SignalSource.NEWS,
            "webhook": SignalSource.WEBHOOK,
            "manual": SignalSource.MANUAL,
        }
        signal_source = source_map.get(source.lower(), SignalSource.DISCORD)

        if confidence >= 0.7:
            strength = SignalStrength.STRONG
        elif confidence >= 0.5:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        signal = Signal(
            source=signal_source,
            symbol=ticker,
            direction=direction,
            raw_message=content,
            parsed_text=content[:500],
            confidence=confidence,
            strength=strength,
            suggested_entry=entry_price,
            suggested_stop=stop_price,
            suggested_target=target_price,
            timeframe=timeframe,
            metadata={**metadata, "raw_message_id": raw_message_id},
        )

        await self._repo.save_signal(signal)

        parsed_event = ParsedTradeIdea(
            aggregate_id=signal.signal_id,
            raw_message_id=raw_message_id,
            symbol=ticker,
            direction=direction,
            asset_class=signal.asset_class,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            timeframe=timeframe,
            parser_confidence=confidence,
        )
        try:
            await self._publisher.publish(KafkaTopics.PARSED_IDEAS, parsed_event)
        except Exception as e:
            logger.warning("Kafka publish failed (non-fatal): %s", e)

        self._parsed_count += 1
        logger.info(
            "Parsed signal [%s]: %s %s @ %s (confidence=%.2f)",
            signal.signal_id, direction.value.upper(), ticker, entry_price, confidence,
        )
        return signal

    @property
    def stats(self) -> dict:
        return {
            "parsed": self._parsed_count,
            "failed": self._failed_count,
            "success_rate": self._parsed_count / max(1, self._parsed_count + self._failed_count),
        }


__all__ = ["ParserService", "extract_ticker", "extract_direction", "compute_confidence"]

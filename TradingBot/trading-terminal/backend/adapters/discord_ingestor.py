"""
Discord message ingestion adapter.
Monitors Discord channels and emits RawMessageReceived events.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Ticker pattern: $AAPL, $TSLA, or plain uppercase 1-5 char words
TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})|(?<!\w)([A-Z]{2,5})(?!\w)")
DIRECTIONAL_WORDS = {
    "buy", "long", "bull", "calls", "call", "entry", "buying",
    "sell", "short", "bear", "puts", "put", "exit", "selling",
}


def extract_potential_tickers(text: str) -> list[str]:
    """Quick pre-filter to check if message is trade-relevant."""
    matches = TICKER_PATTERN.findall(text.upper())
    return [m[0] or m[1] for m in matches if m[0] or m[1]]


def is_trade_relevant(content: str) -> bool:
    """Heuristic: does this message look like a trade signal?"""
    lower = content.lower()
    has_direction = any(word in lower for word in DIRECTIONAL_WORDS)
    has_ticker = bool(extract_potential_tickers(content))
    has_price = bool(re.search(r"\$?\d+\.?\d*", content))
    return has_direction and (has_ticker or has_price)


MessageHandler = Callable[[str, str, str, str, dict[str, Any]], Awaitable[None]]


class DiscordIngestor:
    """
    Discord bot adapter that listens to configured channels
    and forwards trade-relevant messages to the ingestion service.
    """

    def __init__(
        self,
        token: str,
        monitored_channels: list[str] | None = None,
        message_handler: MessageHandler | None = None,
        filter_trade_relevant: bool = True,
    ) -> None:
        self._token = token
        self._monitored_channels: set[str] = set(monitored_channels or [])
        self._message_handler = message_handler
        self._filter_trade_relevant = filter_trade_relevant
        self._client: Any = None
        self._running = False
        self._processed_count = 0

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._message_handler = handler

    async def start(self) -> None:
        """Start the Discord bot. Runs until stop() is called."""
        try:
            import discord  # type: ignore
        except ImportError:
            logger.error("discord.py not installed — Discord ingestor disabled")
            return

        intents = discord.Intents.default()
        intents.message_content = True

        self._client = discord.Client(intents=intents)
        ingestor = self

        @self._client.event
        async def on_ready() -> None:
            logger.info(
                "Discord ingestor connected as %s (monitoring: %s)",
                self._client.user,
                ingestor._monitored_channels or "all channels",
            )
            ingestor._running = True

        @self._client.event
        async def on_message(message: Any) -> None:
            # Skip bot messages
            if message.author.bot:
                return

            # Filter to monitored channels
            channel_name = str(message.channel)
            channel_id = str(message.channel.id)
            if ingestor._monitored_channels and channel_name not in ingestor._monitored_channels:
                return

            content = message.content or ""

            # Optionally filter for trade-relevant content
            if ingestor._filter_trade_relevant and not is_trade_relevant(content):
                return

            ingestor._processed_count += 1
            logger.debug(
                "Discord message [#%s] from %s: %.100s",
                channel_name, message.author.name, content,
            )

            if ingestor._message_handler:
                attachments = [str(a.url) for a in message.attachments]
                metadata: dict[str, Any] = {
                    "guild_id": str(message.guild.id) if message.guild else None,
                    "guild_name": str(message.guild.name) if message.guild else None,
                    "message_id": str(message.id),
                    "attachments": attachments,
                    "potential_tickers": extract_potential_tickers(content),
                }
                try:
                    await ingestor._message_handler(
                        channel_id,
                        channel_name,
                        str(message.author.name),
                        content,
                        metadata,
                    )
                except Exception as exc:
                    logger.error("Message handler error: %s", exc)

        try:
            await self._client.start(self._token)
        except Exception as exc:
            logger.error("Discord bot error: %s", exc)
            raise

    async def stop(self) -> None:
        """Gracefully stop the Discord bot."""
        self._running = False
        if self._client:
            await self._client.close()
        logger.info("Discord ingestor stopped (processed %d messages)", self._processed_count)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def processed_count(self) -> int:
        return self._processed_count


__all__ = ["DiscordIngestor", "is_trade_relevant", "extract_potential_tickers"]

"""
analysts/discord/gateway.py — Single Discord WebSocket process.

One gateway process connects to Discord, subscribes to all configured channels,
and dispatches incoming messages to per-analyst asyncio queues by channel_id.

Run via:
    doppler run -- python scripts/run_discord_gateway.py

Architecture:
    - discord.py Client (one WebSocket per shard)
    - Each channel maps to a list of asyncio.Queue[dict] consumers
    - History replay on ready: last 50 messages per channel, re-delivered if < 30 min old
    - Sanitizer strips zero-width Unicode before dispatch
    - Only dispatches text channel messages (type 0)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

import discord
import httpx

from core.sanitizer import sanitize

logger = logging.getLogger("discord.gateway")

# How far back to replay history on connect
_REPLAY_WINDOW_MINUTES = 30
_HISTORY_FETCH_LIMIT = 50

# Discord REST API for history replay
_API_BASE = "https://discord.com/api/v10"


class DiscordGateway:
    """
    Single Discord WebSocket process. Routes messages to analyst queues by channel_id.

    Usage:
        gateway = DiscordGateway(token, server_id)
        gateway.subscribe(channel_id="123", queue=analyst_queue)
        await gateway.run()
    """

    def __init__(self, token: str, server_id: str) -> None:
        self._token = token
        self._server_id = server_id
        self._subscriptions: dict[str, list[asyncio.Queue[dict]]] = {}
        self._sell_subscriptions: dict[str, list[asyncio.Queue[dict]]] = {}

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        self._client.event(self._on_ready)
        self._client.event(self._on_message)

    # ─── Public API ───────────────────────────────────────────────────────

    def subscribe(self, channel_id: str, queue: "asyncio.Queue[dict]") -> None:
        """Register an analyst queue to receive messages from this channel_id."""
        self._subscriptions.setdefault(channel_id, []).append(queue)

    def subscribe_sell(self, channel_id: str, queue: "asyncio.Queue[dict]") -> None:
        """
        Register a queue to receive ALL messages from this channel (sell signal monitoring).
        Used by Monitor Agent to watch for exit signals.
        """
        self._sell_subscriptions.setdefault(channel_id, []).append(queue)

    async def run(self) -> None:
        logger.info("Discord gateway starting — server=%s", self._server_id)
        await self._client.start(self._token)

    async def close(self) -> None:
        await self._client.close()

    # ─── Events ──────────────────────────────────────────────────────────

    async def _on_ready(self) -> None:
        logger.info(
            "Discord gateway connected | bot=%s | watching %d channel(s)",
            self._client.user,
            len(self._subscriptions),
        )
        # Replay recent history for each subscribed channel
        for channel_id in self._subscriptions:
            asyncio.create_task(
                self._replay_history(channel_id),
                name=f"replay_{channel_id}",
            )

    async def _on_message(self, message: discord.Message) -> None:
        if not isinstance(message.channel, discord.TextChannel):
            return

        channel_id = str(message.channel.id)
        queues = self._subscriptions.get(channel_id, [])
        sell_queues = self._sell_subscriptions.get(channel_id, [])

        if not queues and not sell_queues:
            return

        payload = self._to_payload(message)
        all_queues = list(queues) + list(sell_queues)
        for q in all_queues:
            await q.put(payload)

    # ─── History replay ───────────────────────────────────────────────────

    async def _replay_history(self, channel_id: str) -> None:
        """
        Fetch last N messages from channel via REST. Re-deliver any message
        that arrived within the replay window (prevents missed signals on reconnect).
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=_REPLAY_WINDOW_MINUTES)
        messages = await asyncio.to_thread(
            self._fetch_channel_history, channel_id, _HISTORY_FETCH_LIMIT
        )

        replayed = 0
        for raw_msg in reversed(messages):  # oldest → newest
            ts_str = raw_msg.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            if ts < cutoff:
                continue

            payload = self._raw_to_payload(raw_msg)
            queues = self._subscriptions.get(channel_id, [])
            sell_queues = self._sell_subscriptions.get(channel_id, [])
            for q in list(queues) + list(sell_queues):
                await q.put(payload)
            replayed += 1

        if replayed:
            logger.info("Replayed %d messages for channel %s", replayed, channel_id)

    def _fetch_channel_history(self, channel_id: str, limit: int) -> list[dict]:
        """Blocking REST call — run via asyncio.to_thread."""
        headers = {"Authorization": f"Bot {self._token}"}
        try:
            resp = httpx.get(
                f"{_API_BASE}/channels/{channel_id}/messages",
                headers=headers,
                params={"limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("History fetch failed for channel %s: %s", channel_id, exc)
            return []

    # ─── Message → dict ───────────────────────────────────────────────────

    def _to_payload(self, message: discord.Message) -> dict:
        """Convert discord.py Message to a plain dict for analyst queues."""
        author = message.author
        return {
            "message_id": str(message.id),
            "channel_id": str(message.channel.id),
            "timestamp": message.created_at.isoformat(),
            "author_id": str(author.id),
            "author_name": author.display_name or author.name,
            "author_global_name": getattr(author, "global_name", None) or author.name,
            "is_bot": author.bot,
            "content_raw": message.content,
            "content": sanitize(message.content).text,
            "embeds": [e.to_dict() for e in message.embeds],
        }

    def _raw_to_payload(self, raw: dict) -> dict:
        """Convert raw REST API message dict to the same shape as _to_payload."""
        author = raw.get("author", {})
        content_raw = raw.get("content", "")
        return {
            "message_id": raw.get("id", ""),
            "channel_id": raw.get("channel_id", ""),
            "timestamp": raw.get("timestamp", ""),
            "author_id": author.get("id", ""),
            "author_name": author.get("global_name") or author.get("username", ""),
            "author_global_name": author.get("global_name") or author.get("username", ""),
            "is_bot": author.get("bot", False),
            "content_raw": content_raw,
            "content": sanitize(content_raw).text,
            "embeds": raw.get("embeds", []),
        }


def build_gateway_from_env() -> DiscordGateway:
    """Construct gateway from environment variables (set by Doppler)."""
    token = os.environ["DISCORD_BOT_TOKEN"]
    server_id = os.environ["DISCORD_SERVER_ID"]
    return DiscordGateway(token=token, server_id=server_id)

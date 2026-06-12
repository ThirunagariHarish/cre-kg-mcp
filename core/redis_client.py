"""
core/redis_client.py — Redis singleton with heartbeat and idempotency cache.

Design:
  - One Redis client per process (singleton via module-level variable)
  - Heartbeat: each analyst writes a TTL=90s key every 30s
  - Idempotency: client_order_id cached for 24h to prevent duplicate orders
  - Kill switch: also readable from Redis (dual-read with file fallback)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_REDIS_CLIENT: Redis | None = None

# Key prefixes — namespace everything so Redis is shared across services
HEARTBEAT_PREFIX = "analyst:hb:"         # analyst:hb:{analyst_id}  TTL=90s
IDEMPOTENCY_PREFIX = "analyst:order:"    # analyst:order:{client_order_id}  TTL=86400s
KILL_SWITCH_KEY = "analyst:kill_switch"  # "1" = blocked, "0" = healthy


def get_redis() -> Redis:
    """Return the process-level Redis client. Must call init_redis() first."""
    if _REDIS_CLIENT is None:
        raise RuntimeError("Redis not initialized — call init_redis() at startup")
    return _REDIS_CLIENT


async def init_redis(url: str = "redis://localhost:6379/0") -> Redis:
    """
    Initialize the singleton Redis client.
    Call this ONCE at process startup, before starting any analysts.
    """
    global _REDIS_CLIENT
    client: Redis = aioredis.from_url(url, decode_responses=True)
    await client.ping()  # fast connectivity check
    _REDIS_CLIENT = client
    logger.info("Redis connected: %s", url)
    return client


async def close_redis() -> None:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        await _REDIS_CLIENT.aclose()
        _REDIS_CLIENT = None
        logger.info("Redis connection closed")


# ─────────────────────────────────────────────
# Heartbeat
# ─────────────────────────────────────────────

async def write_heartbeat(analyst_id: str, extra: dict[str, Any] | None = None) -> None:
    """
    Write a heartbeat for analyst_id with TTL=90s.
    If no heartbeat is written in 90s, the analyst is considered dead.

    Legacy lesson: heartbeat MUST be the first thing started in main().
    If you start it after any awaitable, a deadlock can prevent it from running.
    """
    client = get_redis()
    payload: dict[str, Any] = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "analyst_id": analyst_id,
    }
    if extra:
        payload.update(extra)

    import json
    key = f"{HEARTBEAT_PREFIX}{analyst_id}"
    await client.setex(key, 90, json.dumps(payload, default=str))


async def heartbeat_loop(analyst_id: str, interval_seconds: int = 30) -> None:
    """Run forever, writing a heartbeat every interval_seconds."""
    while True:
        try:
            await write_heartbeat(analyst_id)
        except Exception as exc:
            logger.error("Heartbeat write failed for %s: %s", analyst_id, exc)
        await asyncio.sleep(interval_seconds)


# ─────────────────────────────────────────────
# Idempotency cache (duplicate order prevention)
# ─────────────────────────────────────────────

async def check_idempotency(client_order_id: str) -> dict[str, Any] | None:
    """
    Returns the cached result if this client_order_id was already processed.
    Returns None if this is a new order.
    """
    import json
    client = get_redis()
    key = f"{IDEMPOTENCY_PREFIX}{client_order_id}"
    raw = await client.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except Exception:
        return None


async def set_idempotency(client_order_id: str, result: dict[str, Any], ttl: int = 86400) -> None:
    """
    Cache the result of an order submission for `ttl` seconds (default 24h).
    """
    import json
    client = get_redis()
    key = f"{IDEMPOTENCY_PREFIX}{client_order_id}"
    await client.setex(key, ttl, json.dumps(result, default=str))


# ─────────────────────────────────────────────
# Kill switch (Redis tier — checked before file)
# ─────────────────────────────────────────────

async def is_kill_switch_active() -> bool | None:
    """
    Check the Redis kill switch key.
    Returns True/False if key exists, None if key is absent (caller should fall back to file).
    """
    try:
        client = get_redis()
        val = await client.get(KILL_SWITCH_KEY)
        if val is None:
            return None
        return val == "1"
    except Exception as exc:
        logger.warning("Redis kill switch check failed: %s — falling back to file", exc)
        return None


async def set_kill_switch_redis(active: bool) -> None:
    """Set the Redis kill switch. Used by dashboard / operator commands."""
    client = get_redis()
    await client.set(KILL_SWITCH_KEY, "1" if active else "0")

"""
Redis client — connection management and common helpers.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_redis: Any = None


async def init_redis(url: str = "redis://localhost:6379/0") -> Any:
    """Initialize the Redis connection pool."""
    global _redis
    try:
        import redis.asyncio as aioredis  # type: ignore

        _redis = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=10,
        )
        await _redis.ping()
        logger.info("Redis connected: %s", url.split("@")[-1])
        return _redis
    except ImportError:
        logger.warning("redis package not installed — Redis disabled")
        return None
    except Exception as exc:
        logger.error("Redis connection failed: %s", exc)
        return None


def get_redis() -> Any:
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed")


async def cache_set(key: str, value: Any, ttl: int = 300) -> bool:
    """Set a JSON-serialized value in Redis."""
    if not _redis:
        return False
    try:
        await _redis.setex(key, ttl, json.dumps(value, default=str))
        return True
    except Exception as exc:
        logger.error("Redis SET failed for %s: %s", key, exc)
        return False


async def cache_get(key: str) -> Any | None:
    """Get a JSON-deserialized value from Redis."""
    if not _redis:
        return None
    try:
        raw = await _redis.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.error("Redis GET failed for %s: %s", key, exc)
        return None


async def cache_delete(key: str) -> bool:
    """Delete a key from Redis."""
    if not _redis:
        return False
    try:
        await _redis.delete(key)
        return True
    except Exception as exc:
        logger.error("Redis DEL failed for %s: %s", key, exc)
        return False


async def publish_message(channel: str, message: dict[str, Any]) -> None:
    """Publish a message to a Redis pub/sub channel."""
    if not _redis:
        return
    try:
        await _redis.publish(channel, json.dumps(message, default=str))
    except Exception as exc:
        logger.error("Redis PUBLISH failed on %s: %s", channel, exc)


__all__ = [
    "init_redis", "get_redis", "close_redis",
    "cache_set", "cache_get", "cache_delete", "publish_message",
]

"""
WebSocket handlers for live data push to frontend.
Streams portfolio updates, order fills, and signal events via unified /ws endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..infrastructure.redis_client import get_redis

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        logger.info("WebSocket connected (total=%d)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        logger.info("WebSocket disconnected (total=%d)", len(self._connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        if not self._connections:
            return
        disconnected = set()
        for ws in self._connections.copy():
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            self.disconnect(ws)

    async def send_to(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


@router.websocket("/ws")
async def unified_ws(websocket: WebSocket) -> None:
    """Unified WebSocket endpoint — all event types multiplexed on one connection."""
    await manager.connect(websocket)
    try:
        # Send initial snapshot
        await websocket.send_json({"type": "connected", "data": {"status": "ok"}})

        redis = get_redis()
        if redis:
            pubsub = redis.pubsub()
            await pubsub.subscribe("ws:events")
            try:
                while True:
                    # Check Redis messages
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                    if message and message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            await websocket.send_json(data)
                        except Exception:
                            pass
                    # Handle ping from client (non-blocking)
                    try:
                        msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                        if msg.get("type") == "ping":
                            await websocket.send_json({"type": "pong"})
                    except asyncio.TimeoutError:
                        pass
                    except Exception:
                        pass
            finally:
                try:
                    await pubsub.unsubscribe("ws:events")
                except Exception:
                    pass
        else:
            # No Redis — send heartbeats
            while True:
                await asyncio.sleep(10)
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning("WebSocket error: %s", e)
        manager.disconnect(websocket)


@router.websocket("/ws/portfolio")
async def portfolio_ws(websocket: WebSocket) -> None:
    """Backward-compat alias — delegates to unified WS logic."""
    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "channel": "portfolio"})

        redis = get_redis()
        if redis:
            pubsub = redis.pubsub()
            await pubsub.subscribe("ws:events")
            try:
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            await websocket.send_json(data)
                        except (json.JSONDecodeError, Exception):
                            pass
                    try:
                        client_msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                        if client_msg.get("type") == "ping":
                            await websocket.send_json({"type": "pong"})
                    except asyncio.TimeoutError:
                        pass
                    except Exception:
                        pass
            finally:
                try:
                    await pubsub.unsubscribe("ws:events")
                except Exception:
                    pass
        else:
            while True:
                await asyncio.sleep(5)
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.websocket("/ws/orders")
async def orders_ws(websocket: WebSocket) -> None:
    """Backward-compat alias for order updates."""
    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "channel": "orders"})
        while True:
            await asyncio.sleep(5)
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.websocket("/ws/signals")
async def signals_ws(websocket: WebSocket) -> None:
    """Backward-compat alias for signal events."""
    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "channel": "signals"})
        while True:
            await asyncio.sleep(5)
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_event(event_type: str, data: Any) -> None:
    """
    Broadcast an event to all WebSocket connections AND to Redis pub/sub.
    Both paths are non-fatal.
    """
    message = {
        "type": event_type,
        "data": data,
        "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    # Direct WebSocket broadcast
    try:
        await manager.broadcast(message)
    except Exception as e:
        logger.warning("WS broadcast failed: %s", e)

    # Redis pub/sub for any other subscribers
    redis = get_redis()
    if redis:
        try:
            await redis.publish("ws:events", json.dumps(message, default=str))
        except Exception as e:
            logger.warning("Redis publish failed: %s", e)


__all__ = ["router", "manager", "broadcast_event"]

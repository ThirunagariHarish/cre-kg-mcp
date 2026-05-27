"""Robinhood Execution Service — singleton queue consumer.

Consumes from Redis list 'rh:trade_queue'.
Applies risk gate, executes via RobinhoodMCPClient, spawns position monitors.

Trade message format (JSON):
{
  "message_id": "uuid",
  "agent_id": "breakout_trader",
  "ticker": "AAPL",
  "side": "long",                    # "long" | "short"
  "option_type": "call",             # null for stock
  "strike": 190.0,                   # null for stock
  "expiry": "2025-06-20",            # null for stock
  "quantity": 2,
  "confidence": 0.85,
  "stop_loss_pct": 25.0,
  "take_profit_pct": 50.0,           # for options: % of premium
  "max_position_pct": 5.0,
  "rationale": "Breakout above 52w high with 3x volume",
  "signal_id": "uuid",
  "priority": 5,
  "ts": 1700000000000
}
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..adapters.robinhood_mcp_client import RobinhoodMCPClient
from ..infrastructure.redis_client import get_redis
from ..api.websockets import broadcast_event

logger = logging.getLogger(__name__)

QUEUE_KEY = "rh:trade_queue"
POSITIONS_KEY = "rh:positions"    # Hash: position_id → JSON
REJECTED_KEY = "rh:rejected"      # List of rejected trade messages


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


class RobinhoodExecutionService:
    """
    Singleton execution engine.
    One instance per application — started in FastAPI lifespan.
    """

    def __init__(self, paper_mode: bool = True) -> None:
        self.paper_mode = paper_mode
        self._mcp: RobinhoodMCPClient | None = None
        self._running = False
        self._logged_in = False
        self._open_positions: dict[str, dict[str, Any]] = {}  # position_id → position
        self._monitor_tasks: dict[str, asyncio.Task] = {}     # position_id → task

    async def start(self) -> None:
        """Call from FastAPI lifespan startup."""
        self._mcp = RobinhoodMCPClient(paper_mode=self.paper_mode)
        self._running = True

        # Login to Robinhood
        try:
            result = self._mcp.login()
            if result.get("success") or result.get("logged_in") or result.get("status") == "logged_in":
                self._logged_in = True
                logger.info("Robinhood login success (paper=%s)", self.paper_mode)
            else:
                logger.warning("Robinhood login failed: %s — execution will run in dry-run mode", result)
        except Exception as e:
            logger.warning("Robinhood login error: %s — execution will run in dry-run mode", e)

        logger.info("RobinhoodExecutionService started (paper=%s logged_in=%s)", self.paper_mode, self._logged_in)

    async def stop(self) -> None:
        """Call from FastAPI lifespan shutdown."""
        self._running = False
        # Cancel all monitor tasks
        for task in self._monitor_tasks.values():
            task.cancel()
        if self._mcp:
            self._mcp.shutdown()
        logger.info("RobinhoodExecutionService stopped")

    async def run_queue_loop(self) -> None:
        """Main loop — run as asyncio task from FastAPI lifespan."""
        logger.info("Execution queue loop started")
        while self._running:
            try:
                await self._process_next()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Queue loop error: %s", e)
            await asyncio.sleep(0.1)  # 100ms poll

    async def enqueue(self, trade: dict[str, Any]) -> str:
        """Enqueue a trade message. Returns message_id."""
        if "message_id" not in trade:
            trade["message_id"] = str(uuid.uuid4())
        if "ts" not in trade:
            trade["ts"] = _now_ms()
        redis = get_redis()
        if redis:
            await redis.lpush(QUEUE_KEY, json.dumps(trade))
        return trade["message_id"]

    async def get_queue_depth(self) -> int:
        redis = get_redis()
        if redis:
            return await redis.llen(QUEUE_KEY)
        return 0

    async def get_open_positions(self) -> list[dict[str, Any]]:
        return list(self._open_positions.values())

    async def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "logged_in": self._logged_in,
            "paper_mode": self.paper_mode,
            "queue_depth": await self.get_queue_depth(),
            "open_positions": len(self._open_positions),
            "monitor_tasks": len(self._monitor_tasks),
        }

    async def _process_next(self) -> None:
        """Pop and process one message from the queue."""
        redis = get_redis()
        if not redis:
            return
        raw = await redis.rpop(QUEUE_KEY)
        if not raw:
            return

        try:
            msg = json.loads(raw)
        except Exception:
            logger.error("Invalid JSON in trade queue: %s", raw[:100])
            return

        msg_id = msg.get("message_id", "?")
        msg_type = msg.get("message_type", "EXECUTE_TRADE")

        try:
            if msg_type == "EXECUTE_TRADE" or "ticker" in msg:
                await self._handle_execute(msg)
            elif msg_type == "CLOSE_POSITION":
                await self._handle_close(msg)
        except Exception as e:
            logger.error("Error processing trade %s: %s", msg_id, e, exc_info=True)
            # Push to rejected list
            msg["error"] = str(e)
            msg["rejected_at"] = _now_iso()
            redis = get_redis()
            if redis:
                await redis.lpush(REJECTED_KEY, json.dumps(msg))

    async def _handle_execute(self, msg: dict[str, Any]) -> None:
        ticker = msg.get("ticker", "")
        agent_id = msg.get("agent_id", "unknown")
        option_type = msg.get("option_type")
        strike = msg.get("strike")
        expiry = msg.get("expiry")
        quantity = int(msg.get("quantity", 1))
        confidence = float(msg.get("confidence", 0.0))
        stop_loss_pct = float(msg.get("stop_loss_pct", 25.0))
        take_profit_pct = float(msg.get("take_profit_pct", 50.0))
        rationale = msg.get("rationale", "")

        logger.info(
            "Executing trade: agent=%s ticker=%s option=%s/%s/%s qty=%d confidence=%.0f%%",
            agent_id, ticker, option_type, strike, expiry, quantity, confidence * 100
        )

        # Risk check: min confidence 60%
        if confidence < 0.60:
            logger.warning("Trade rejected — confidence %.0f%% below 60%% gate", confidence * 100)
            return

        # Execute via MCP
        if not self._mcp or not self._logged_in:
            logger.warning("Skipping execution — not logged in")
            return

        try:
            if option_type and strike and expiry:
                result = self._mcp.place_option_order(
                    ticker, expiry, float(strike), option_type, quantity, "buy"
                )
            else:
                result = self._mcp.place_stock_order(ticker, quantity, "buy")

            logger.info("Order result for %s: %s", ticker, result)

            # Record open position
            position_id = str(uuid.uuid4())
            position = {
                "position_id": position_id,
                "agent_id": agent_id,
                "ticker": ticker,
                "option_type": option_type,
                "strike": strike,
                "expiry": expiry,
                "quantity": quantity,
                "entry_price": result.get("price") or result.get("fill_price") or 0.0,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "rationale": rationale,
                "opened_at": _now_iso(),
                "status": "OPEN",
                "order_id": result.get("id") or result.get("order_id"),
            }
            self._open_positions[position_id] = position

            # Persist to Redis
            redis = get_redis()
            if redis:
                await redis.hset(POSITIONS_KEY, position_id, json.dumps(position))

            # Broadcast
            await broadcast_event("POSITION_OPENED", position)

            # Spawn monitor task
            monitor_task = asyncio.create_task(
                self._monitor_position(position_id)
            )
            self._monitor_tasks[position_id] = monitor_task
            logger.info("Monitor spawned for position %s (%s)", position_id[:8], ticker)

        except Exception as e:
            logger.error("Order execution failed for %s: %s", ticker, e)
            raise

    async def _handle_close(self, msg: dict[str, Any]) -> None:
        position_id = msg.get("position_id")
        ticker = msg.get("ticker", "")
        if not self._mcp:
            return
        try:
            result = self._mcp.close_position(ticker)
            logger.info("Closed position %s (%s): %s", position_id, ticker, result)
            if position_id and position_id in self._open_positions:
                pos = self._open_positions.pop(position_id)
                pos["status"] = "CLOSED"
                pos["closed_at"] = _now_iso()
                await broadcast_event("POSITION_CLOSED", pos)
        except Exception as e:
            logger.error("Close position failed for %s: %s", ticker, e)

    async def _monitor_position(self, position_id: str) -> None:
        """Monitor a single open position. Close at profit target or stop loss."""
        POLL_SEC = 30
        MAX_HOLD_MIN = 480  # 8 hours max hold

        pos = self._open_positions.get(position_id)
        if not pos:
            return

        ticker = pos["ticker"]
        entry_price = float(pos.get("entry_price") or 0.0)
        take_profit_pct = float(pos.get("take_profit_pct") or 50.0)
        stop_loss_pct = float(pos.get("stop_loss_pct") or 25.0)
        quantity = int(pos.get("quantity") or 1)

        logger.info(
            "Position monitor started: %s entry=%.2f tp=%.0f%% sl=%.0f%%",
            ticker, entry_price, take_profit_pct, stop_loss_pct
        )

        hold_minutes = 0

        try:
            while position_id in self._open_positions:
                await asyncio.sleep(POLL_SEC)
                hold_minutes += POLL_SEC / 60

                if not self._mcp:
                    break

                # Get current quote
                try:
                    quote = self._mcp.get_quote(ticker)
                    current_price = float(
                        quote.get("ask_price") or quote.get("last_trade_price") or quote.get("last_price") or quote.get("price") or entry_price
                    )
                except Exception as e:
                    logger.warning("Quote fetch failed for %s: %s", ticker, e)
                    continue

                if entry_price <= 0:
                    entry_price = current_price
                    pos["entry_price"] = entry_price
                    continue

                change_pct = ((current_price - entry_price) / entry_price) * 100
                pos["current_price"] = current_price
                pos["unrealized_pnl_pct"] = change_pct

                await broadcast_event("POSITION_UPDATE_MONITOR", {
                    "position_id": position_id,
                    "ticker": ticker,
                    "current_price": current_price,
                    "change_pct": round(change_pct, 2),
                    "hold_minutes": round(hold_minutes, 1),
                })

                should_close = False
                close_reason = ""

                if change_pct >= take_profit_pct:
                    should_close = True
                    close_reason = f"TAKE_PROFIT +{change_pct:.1f}% >= +{take_profit_pct:.0f}%"
                elif change_pct <= -stop_loss_pct:
                    should_close = True
                    close_reason = f"STOP_LOSS {change_pct:.1f}% <= -{stop_loss_pct:.0f}%"
                elif hold_minutes >= MAX_HOLD_MIN:
                    should_close = True
                    close_reason = f"MAX_HOLD {hold_minutes:.0f}min reached"

                if should_close:
                    logger.info("Closing position %s (%s): %s", position_id[:8], ticker, close_reason)
                    try:
                        if self._mcp:
                            self._mcp.close_position(ticker, quantity)
                    except Exception as e:
                        logger.error("Failed to close %s: %s", ticker, e)

                    pos["status"] = "CLOSED"
                    pos["close_reason"] = close_reason
                    pos["closed_at"] = _now_iso()
                    pos["exit_price"] = current_price
                    pos["realized_pnl_pct"] = change_pct
                    self._open_positions.pop(position_id, None)

                    redis = get_redis()
                    if redis:
                        await redis.hdel(POSITIONS_KEY, position_id)

                    await broadcast_event("POSITION_CLOSED", pos)
                    break

        except asyncio.CancelledError:
            logger.info("Monitor task cancelled for %s", position_id[:8])
        finally:
            self._monitor_tasks.pop(position_id, None)


# Singleton instance — set in FastAPI lifespan
_execution_service: RobinhoodExecutionService | None = None


def set_execution_service(svc: RobinhoodExecutionService) -> None:
    global _execution_service
    _execution_service = svc


def get_execution_service() -> RobinhoodExecutionService | None:
    return _execution_service


__all__ = ["RobinhoodExecutionService", "set_execution_service", "get_execution_service"]

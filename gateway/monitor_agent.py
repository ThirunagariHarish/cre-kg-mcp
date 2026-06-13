"""
gateway/monitor_agent.py — M1.5 Monitor Agent

Manages exit of all open positions using per-position exit strategies.
Runs a poll loop every 30 seconds. Applies hard stops universally.
Sends Telegram alerts. Persists state to shared/state/open_positions.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from core.file_writer import append_jsonl, atomic_write_json, read_json
from core.schemas import ExitStrategy, PositionRecord

logger = logging.getLogger(__name__)

OPEN_POSITIONS_FILE = Path("shared/state/open_positions.json")
TA_SIGNAL_FILE = Path("shared/state/ta_signal.json")
TA_CONTRADICTIONS_FILE = Path("shared/state/ta_contradictions.jsonl")
MONITOR_RL_DATA_FILE = Path("shared/state/monitor_rl_data.jsonl")

# TA check runs every 5 minutes (300 seconds)
TA_CHECK_INTERVAL_SECONDS: int = 300


# ─────────────────────────────────────────────
# RHGateway Protocol — allows test mocking
# ─────────────────────────────────────────────

class RHGateway(Protocol):
    """Minimal interface the MonitorAgent needs from the Robinhood gateway."""

    async def get_quote(
        self,
        symbol: str,
        direction: str,
        strike: float,
        expiry: Any,
    ) -> float | None:
        """Return mark price per share, or None if unavailable."""
        ...

    async def close_position(
        self,
        position: PositionRecord,
        qty: int,
        reason: str,
    ) -> bool:
        """Submit a closing order. Returns True on success."""
        ...

    async def get_positions(self) -> list[PositionRecord]:
        """Return all currently open positions."""
        ...

    @property
    def paper_mode(self) -> bool:
        """True if running in paper trading mode."""
        ...


# ─────────────────────────────────────────────
# MonitorAgent
# ─────────────────────────────────────────────

class MonitorAgent:
    """
    Monitors all open positions and applies exit logic every poll_interval_seconds.

    Hard stops (non-negotiable, all strategies):
      - HARD_STOP_LOSS_PCT = -0.50  (close at -50% loss)
      - HARD_TAKE_PROFIT_PCT = 1.00  (close at +100% gain)

    Market close sweep: close ALL positions 5 min before 4:00 PM ET.
    """

    HARD_STOP_LOSS_PCT: float = -0.50
    HARD_TAKE_PROFIT_PCT: float = 1.00
    MARKET_CLOSE_SWEEP_MINUTES: int = 5

    def __init__(
        self,
        gateway: RHGateway,
        sell_queues: dict[str, asyncio.Queue[dict]],
        *,
        poll_interval_seconds: int = 30,
    ) -> None:
        self._gateway = gateway
        self._sell_queues = sell_queues
        self._poll_interval = poll_interval_seconds

        # position_id -> PositionRecord (mutable tracking via replacement)
        self._positions: dict[str, PositionRecord] = {}

        # position_id -> datetime of last sell message seen (for OWNER_LAST_SELL)
        self._last_sell_time: dict[str, datetime] = {}

        # position_id -> has_sold_partial override (since PositionRecord is frozen)
        self._partial_state: dict[str, dict] = {}  # {has_sold_partial, partial_qty_sold}

        # position_id -> datetime of last TA contradiction check (5-minute interval)
        self._last_ta_check: dict[str, datetime] = {}

        self._running = False
        self._http: httpx.AsyncClient | None = None

        # Telegram config
        self._tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main loop — polls positions every poll_interval_seconds."""
        self._running = True
        self._http = httpx.AsyncClient(timeout=10.0)
        self._load_positions()

        logger.info("MonitorAgent started (interval=%ds)", self._poll_interval)

        try:
            while self._running:
                try:
                    await self._poll_positions()
                except Exception:
                    logger.exception("Error in poll cycle — continuing")
                await asyncio.sleep(self._poll_interval)
        finally:
            if self._http:
                await self._http.aclose()
            logger.info("MonitorAgent stopped")

    def stop(self) -> None:
        self._running = False

    def add_position(self, pos: PositionRecord) -> None:
        """Register a new open position. Call this when a fill is confirmed."""
        self._positions[pos.position_id] = pos
        self._partial_state[pos.position_id] = {
            "has_sold_partial": pos.has_sold_partial,
            "partial_qty_sold": pos.partial_qty_sold,
        }
        self._persist_positions()
        logger.info(
            "Position opened: %s %s %s %.0f %s qty=%d @ %.2f",
            pos.analyst_id, pos.symbol, pos.direction,
            pos.strike, pos.expiry, pos.qty, pos.avg_cost_per_share,
        )
        asyncio.create_task(
            self._send_telegram(
                f"POSITION OPENED: {pos.analyst_id} | {pos.symbol} {pos.direction} "
                f"{pos.strike:.0f} {pos.expiry} | qty={pos.qty} @ ${pos.avg_cost_per_share:.2f}"
            )
        )

    # ─── Poll cycle ─────────────────────────────────────────────────────────

    async def _poll_positions(self) -> None:
        """Check all open positions and apply exit logic."""
        await self._process_manual_close_queue()

        if not self._positions:
            return

        # Market close sweep takes priority
        await self._check_market_close()

        # Check each remaining position
        for pid in list(self._positions.keys()):
            pos = self._positions.get(pid)
            if pos is None:
                continue
            try:
                await self._check_position(pos)
            except Exception:
                logger.exception("Error checking position %s", pid)

    async def _check_position(self, pos: PositionRecord) -> None:
        """Apply exit strategy for one position."""
        from gateway.telegram_handler import _load_paused_analysts
        if pos.analyst_id in _load_paused_analysts():
            return  # Analyst paused, skip this position entirely

        current_price = await self._get_price(pos)
        if current_price is None:
            logger.warning("No quote for %s — skipping", pos.position_id)
            return

        # Hard stops always win
        closed = await self._check_hard_stops(pos, current_price)
        if closed:
            return

        # TA cross-check runs every 5 minutes (not every 30s poll)
        now = datetime.now(tz=timezone.utc)
        last_ta = self._last_ta_check.get(pos.position_id)
        if last_ta is None or (now - last_ta).total_seconds() >= TA_CHECK_INTERVAL_SECONDS:
            self._last_ta_check[pos.position_id] = now
            ta_closed = await self._check_ta_contradiction(pos, current_price)
            if ta_closed:
                return

        strategy: ExitStrategy = pos.exit_rules.strategy

        if strategy in ("FIRST_SELL_FROM_SOURCE", "OWNER_FIRST_SELL"):
            await self._handle_first_sell(pos)

        elif strategy == "PARTIAL_SELL_PCT":
            await self._handle_partial_sell(pos)

        elif strategy == "OWNER_LAST_SELL":
            await self._handle_owner_last_sell(pos)

        elif strategy == "PRICE_TARGET":
            await self._handle_price_target(pos, current_price)

        elif strategy == "TA_RULES":
            await self._handle_ta_rules(pos)

        elif strategy == "MANUAL":
            # Never auto-close; human or dashboard only
            pass

    async def _check_hard_stops(self, pos: PositionRecord, current_price: float) -> bool:
        """Apply hard stop-loss and take-profit. Returns True if position was closed."""
        pnl_pct = (current_price - pos.avg_cost_per_share) / pos.avg_cost_per_share

        if pnl_pct <= self.HARD_STOP_LOSS_PCT:
            remaining_qty = self._remaining_qty(pos)
            await self._close_position(
                pos,
                remaining_qty,
                f"HARD_STOP_LOSS {pnl_pct:.1%}",
            )
            return True

        if pnl_pct >= self.HARD_TAKE_PROFIT_PCT:
            remaining_qty = self._remaining_qty(pos)
            await self._close_position(
                pos,
                remaining_qty,
                f"HARD_TAKE_PROFIT {pnl_pct:.1%}",
            )
            return True

        return False

    async def _check_market_close(self) -> None:
        """Close ALL open positions if within MARKET_CLOSE_SWEEP_MINUTES of 4:00 PM ET."""
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        now_et = datetime.now(tz=et)

        # Market close at 16:00 ET
        market_close_hour = 16
        market_close_minute = 0

        # Calculate minutes until market close
        total_now = now_et.hour * 60 + now_et.minute
        total_close = market_close_hour * 60 + market_close_minute
        minutes_until_close = total_close - total_now

        if 0 <= minutes_until_close <= self.MARKET_CLOSE_SWEEP_MINUTES:
            pids = list(self._positions.keys())
            if pids:
                logger.warning(
                    "Market close sweep: %d min until close, closing %d positions",
                    minutes_until_close,
                    len(pids),
                )
                for pid in pids:
                    pos = self._positions.get(pid)
                    if pos:
                        remaining_qty = self._remaining_qty(pos)
                        await self._close_position(
                            pos, remaining_qty, "MARKET_CLOSE_SWEEP"
                        )

    # ─── Strategy handlers ──────────────────────────────────────────────────

    async def _handle_first_sell(self, pos: PositionRecord) -> None:
        """FIRST_SELL_FROM_SOURCE / OWNER_FIRST_SELL: close 100% on first sell message."""
        channel_id = pos.exit_rules.source_channel_id
        if channel_id is None:
            return

        messages = await self._drain_sell_queue(channel_id)
        if messages:
            remaining_qty = self._remaining_qty(pos)
            await self._close_position(
                pos,
                remaining_qty,
                f"{pos.exit_rules.strategy} sell message received",
            )

    async def _handle_partial_sell(self, pos: PositionRecord) -> None:
        """PARTIAL_SELL_PCT: first sell closes partial_sell_pct; second closes remainder."""
        channel_id = pos.exit_rules.source_channel_id
        if channel_id is None:
            return

        messages = await self._drain_sell_queue(channel_id)
        if not messages:
            return

        pstate = self._partial_state[pos.position_id]

        if not pstate["has_sold_partial"]:
            # First sell: close partial_sell_pct
            pct = pos.exit_rules.partial_sell_pct or 0.70
            partial_qty = max(1, round(pos.qty * pct))

            await self._close_position(
                pos,
                partial_qty,
                f"PARTIAL_SELL_PCT first sell ({pct:.0%})",
            )
            # Update partial state AFTER close so _close_position sees correct remaining
            pstate["has_sold_partial"] = True
            pstate["partial_qty_sold"] = partial_qty
            self._persist_positions()
            await self._send_telegram(
                f"PARTIAL SELL: {pos.analyst_id} | {pos.symbol} {pos.direction} "
                f"{pos.strike:.0f} | sold {partial_qty}/{pos.qty} contracts"
            )
        else:
            # Second sell: close remainder
            sold = pstate["partial_qty_sold"]
            remainder = pos.qty - sold
            if remainder > 0:
                await self._close_position(
                    pos,
                    remainder,
                    "PARTIAL_SELL_PCT second sell (remainder)",
                )

    async def _handle_owner_last_sell(self, pos: PositionRecord) -> None:
        """OWNER_LAST_SELL: close when no new sell for owner_silence_seconds."""
        channel_id = pos.exit_rules.source_channel_id
        if channel_id is None:
            return

        messages = await self._drain_sell_queue(channel_id)
        if messages:
            # Update last sell time
            self._last_sell_time[pos.position_id] = datetime.now(tz=timezone.utc)
            return

        # Check silence duration
        last_sell = self._last_sell_time.get(pos.position_id)
        if last_sell is None:
            # Never seen a sell yet — don't close
            return

        elapsed = (datetime.now(tz=timezone.utc) - last_sell).total_seconds()
        silence_threshold = pos.exit_rules.owner_silence_seconds

        if elapsed >= silence_threshold:
            remaining_qty = self._remaining_qty(pos)
            await self._close_position(
                pos,
                remaining_qty,
                f"OWNER_LAST_SELL: {elapsed:.0f}s silence (threshold={silence_threshold}s)",
            )

    async def _handle_price_target(self, pos: PositionRecord, current_price: float) -> None:
        """PRICE_TARGET: close when current_price >= entry * multiplier."""
        multiplier = pos.exit_rules.price_target_multiplier
        if multiplier is None:
            return

        target = pos.avg_cost_per_share * multiplier
        if current_price >= target:
            remaining_qty = self._remaining_qty(pos)
            await self._close_position(
                pos,
                remaining_qty,
                f"PRICE_TARGET hit: {current_price:.2f} >= {target:.2f} ({multiplier}x)",
            )

    async def _handle_ta_rules(self, pos: PositionRecord) -> None:
        """TA_RULES: close when shared/state/ta_signal.json signals reversal."""
        data = read_json(TA_SIGNAL_FILE, default={})
        signal = data.get("signal", "HOLD")

        if signal in ("SELL", "REVERSAL"):
            remaining_qty = self._remaining_qty(pos)
            await self._close_position(
                pos,
                remaining_qty,
                f"TA_RULES: signal={signal}",
            )

    async def _check_ta_contradiction(
        self, pos: PositionRecord, current_price: float
    ) -> bool:
        """
        Cross-check open position against the current TA signal.

        Returns True if the position was closed (TA_RULES strategy + opposite signal).
        Returns False in all other cases (flag only, or no contradiction).
        """
        data = read_json(TA_SIGNAL_FILE, default=None)
        if not isinstance(data, dict):
            return False

        ta_direction: str = data.get("direction", "")
        ta_confidence: float = float(data.get("confidence", 0.0))

        if not ta_direction or ta_direction == "HOLD":
            # No directional signal — nothing to contradict
            if pos.exit_rules.strategy == "TA_RULES":
                # Explicit HOLD: keep holding
                return False
            return False

        # Determine if TA is opposite to current position
        pos_direction = pos.direction  # "CALL" or "PUT"
        is_opposite = (
            (pos_direction == "CALL" and ta_direction == "PUT")
            or (pos_direction == "PUT" and ta_direction == "CALL")
        )

        if not is_opposite:
            return False

        # --- TA_RULES strategy: always auto-close on opposite signal ---
        if pos.exit_rules.strategy == "TA_RULES":
            remaining_qty = self._remaining_qty(pos)
            await self._close_position(pos, remaining_qty, reason="TA_EXIT")
            return True

        # --- Non-TA_RULES: flag for RL training if profitable + high-confidence ---
        pnl_pct = (current_price - pos.avg_cost_per_share) / pos.avg_cost_per_share
        is_profitable = pnl_pct > 0.05
        is_high_confidence = ta_confidence >= 0.65

        if is_profitable and is_high_confidence:
            logger.warning(
                "TA CONTRADICTION: position %s %s contradicted by TA %s "
                "(confidence=%.2f, pnl=%.1f%%)",
                pos.symbol,
                pos.direction,
                ta_direction,
                ta_confidence,
                pnl_pct * 100,
            )
            try:
                append_jsonl(
                    TA_CONTRADICTIONS_FILE,
                    {
                        "position_id": pos.position_id,
                        "analyst_id": pos.analyst_id,
                        "symbol": pos.symbol,
                        "pos_direction": pos_direction,
                        "ta_direction": ta_direction,
                        "ta_confidence": ta_confidence,
                        "pnl_pct": round(pnl_pct, 6),
                        "exit_strategy": pos.exit_rules.strategy,
                        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    },
                )
            except Exception:
                logger.exception("Failed to write TA contradiction record")

        return False

    # ─── Core operations ────────────────────────────────────────────────────

    async def _process_manual_close_queue(self) -> None:
        """Process manual close requests from shared/state/manual_close_queue.jsonl."""
        path = Path("shared/state/manual_close_queue.jsonl")
        if not path.exists():
            return
        try:
            lines = path.read_text().splitlines()
            if not lines:
                return
            path.write_text("")  # clear the queue
        except Exception:
            return
        positions = await self._gateway.get_positions()
        for line in lines:
            try:
                entry = json.loads(line)
                action = entry.get("action", "")
                if action == "close_all":
                    for pos in positions:
                        await self._close_position(pos, pos.qty, "MANUAL_CLOSE_ALL")
                elif action == "close_by_symbol":
                    symbol = entry.get("symbol", "")
                    matching = [p for p in positions if p.symbol == symbol.upper()]
                    for pos in matching:
                        await self._close_position(pos, pos.qty, f"MANUAL_CLOSE_{symbol}")
                elif action == "close_position":
                    pid = entry.get("position_id", "")
                    matching = [p for p in positions if p.position_id == pid]
                    for pos in matching:
                        await self._close_position(pos, pos.qty, "MANUAL_CLOSE_DASHBOARD")
            except Exception as exc:
                logger.error("Manual close queue error: %s", exc)

    async def _drain_sell_queue(self, channel_id: str) -> list[dict]:
        """Non-blocking drain of all pending messages from a sell queue."""
        queue = self._sell_queues.get(channel_id)
        if queue is None:
            return []

        messages: list[dict] = []
        while True:
            try:
                msg = queue.get_nowait()
                messages.append(msg)
            except asyncio.QueueEmpty:
                break

        return messages

    async def _close_position(
        self,
        pos: PositionRecord,
        qty: int,
        reason: str,
    ) -> None:
        """Submit closing order and remove position from tracking."""
        if qty <= 0:
            logger.warning("_close_position called with qty=%d for %s — skipping", qty, pos.position_id)
            return

        logger.info(
            "Closing %s: %s %s %.0f %s qty=%d reason=%s",
            pos.position_id, pos.symbol, pos.direction,
            pos.strike, pos.expiry, qty, reason,
        )

        try:
            success = await self._gateway.close_position(pos, qty, reason)
        except Exception:
            logger.exception("Gateway close_position failed for %s", pos.position_id)
            success = False

        # Determine if this close leaves zero remaining.
        # _remaining_qty reflects the pre-close state; a full close means qty == remaining.
        remaining_before = self._remaining_qty(pos)
        is_full_close = qty >= remaining_before

        if is_full_close:
            # Compute metrics for RL training before removing state
            hold_duration_minutes: float = 0.0
            pnl_pct: float = 0.0
            try:
                hold_duration_minutes = (
                    datetime.now(tz=timezone.utc) - pos.opened_at
                ).total_seconds() / 60.0
            except Exception:
                pass

            # We don't have current_price here, so pnl_pct is left at 0.0.
            # The caller (_check_position) may have it; RL consumers derive it from
            # journal data. Approximate from avg_cost only if gateway gave a price.

            # Determine if TA agreed with the position direction at close time
            ta_agreed: bool = False
            try:
                ta_data = read_json(TA_SIGNAL_FILE, default={})
                ta_dir = ta_data.get("direction", "") if isinstance(ta_data, dict) else ""
                if ta_dir and ta_dir not in ("HOLD", ""):
                    ta_agreed = (
                        (pos.direction == "CALL" and ta_dir == "CALL")
                        or (pos.direction == "PUT" and ta_dir == "PUT")
                    )
            except Exception:
                pass

            # Write RL training record
            try:
                append_jsonl(
                    MONITOR_RL_DATA_FILE,
                    {
                        "position_id": pos.position_id,
                        "analyst_id": pos.analyst_id,
                        "exit_reason": reason,
                        "exit_strategy_used": pos.exit_rules.strategy,
                        "pnl_pct": round(pnl_pct, 6),
                        "hold_duration_minutes": round(hold_duration_minutes, 2),
                        "ta_agreed": ta_agreed,
                        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    },
                )
            except Exception:
                logger.exception("Failed to write monitor RL data record")

            # Remove from tracking
            self._positions.pop(pos.position_id, None)
            self._last_sell_time.pop(pos.position_id, None)
            self._last_ta_check.pop(pos.position_id, None)
            self._partial_state.pop(pos.position_id, None)
            self._persist_positions()

            await self._send_telegram(
                f"POSITION CLOSED: {pos.analyst_id} | {pos.symbol} {pos.direction} "
                f"{pos.strike:.0f} {pos.expiry} | qty={qty} | reason={reason} | "
                f"{'OK' if success else 'GATEWAY_ERROR'}"
            )
        else:
            self._persist_positions()

    async def _get_price(self, pos: PositionRecord) -> float | None:
        """Get current mark price per share."""
        try:
            price = await self._gateway.get_quote(
                pos.symbol, pos.direction, pos.strike, pos.expiry
            )
            if price is not None:
                return price
        except Exception:
            logger.exception("get_quote failed for %s", pos.position_id)

        if getattr(self._gateway, "paper_mode", True):
            # Simulate slight drift for paper mode when no quote available
            drift = random.uniform(-0.05, 0.05)
            return pos.avg_cost_per_share * (1.0 + drift)

        return None

    # ─── State persistence ──────────────────────────────────────────────────

    def _persist_positions(self) -> None:
        """Write open positions to shared/state/open_positions.json atomically."""
        data = []
        for pid, pos in self._positions.items():
            pstate = self._partial_state.get(pid, {})
            record = pos.model_dump(mode="json")
            record["has_sold_partial"] = pstate.get("has_sold_partial", pos.has_sold_partial)
            record["partial_qty_sold"] = pstate.get("partial_qty_sold", pos.partial_qty_sold)
            data.append(record)

        try:
            atomic_write_json(OPEN_POSITIONS_FILE, data)
        except Exception:
            logger.exception("Failed to persist positions")

    def _load_positions(self) -> None:
        """Restore open positions from state file on startup."""
        data = read_json(OPEN_POSITIONS_FILE, default=[])
        if not isinstance(data, list):
            logger.error("open_positions.json is not a list — ignoring")
            return

        loaded = 0
        for record in data:
            try:
                pos = PositionRecord.model_validate(record)
                self._positions[pos.position_id] = pos
                self._partial_state[pos.position_id] = {
                    "has_sold_partial": record.get("has_sold_partial", False),
                    "partial_qty_sold": record.get("partial_qty_sold", 0),
                }
                loaded += 1
            except Exception:
                logger.exception("Failed to restore position: %s", record)

        if loaded:
            logger.info("Restored %d open positions from state file", loaded)

    def _remaining_qty(self, pos: PositionRecord) -> int:
        """Qty not yet sold, accounting for any partial sells."""
        pstate = self._partial_state.get(pos.position_id, {})
        sold = pstate.get("partial_qty_sold", pos.partial_qty_sold)
        return pos.qty - sold

    # ─── Telegram ───────────────────────────────────────────────────────────

    async def _send_telegram(self, msg: str) -> None:
        """Fire-and-forget Telegram alert. Never raises."""
        if not self._tg_token or not self._tg_chat_id:
            logger.debug("Telegram not configured — skipping alert: %s", msg[:80])
            return

        try:
            client = self._http or httpx.AsyncClient(timeout=10.0)
            url = f"https://api.telegram.org/bot{self._tg_token}/sendMessage"
            await client.post(url, json={"chat_id": self._tg_chat_id, "text": msg})
        except Exception:
            logger.warning("Telegram alert failed (non-fatal): %s", msg[:80])

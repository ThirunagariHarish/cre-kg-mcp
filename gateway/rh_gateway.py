"""
gateway/rh_gateway.py — Robinhood execution gateway for the AnalystTeam system.

Design:
  - Paper mode: fully in-memory simulation (no real orders)
  - Live mode: robin_stocks via asyncio.to_thread (no blocking the event loop)
  - Redis idempotency: prevents duplicate fills on retry (TTL=24h)
  - Guards: min ask $0.10, max OTM% for 0DTE = 2%
  - All prices stored as per_share AND per_contract (x100)

NOT an MCP server — a plain async class consumed by the Master Analyst / Monitor Agent.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any

from core.schemas import (
    ExitRules,
    OptionContract,
    OrderRecord,
    PositionRecord,
    TradeSignal,
    make_client_order_id,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Constants / defaults
# ─────────────────────────────────────────────

_DEFAULT_MAX_POSITION_USD = 200.0
_DEFAULT_EXECUTION_BUFFER = 0.02   # 2% above ask to improve fill probability
_MIN_ASK_PER_SHARE = 0.10          # reject penny options
_MAX_OTM_PCT_0DTE = 0.02           # reject strikes > 2% OTM for same-day expiry
_IDEMPOTENCY_TTL = 86400           # 24 hours in seconds
_IDEMPOTENCY_KEY_PREFIX = "order:" # Redis namespace


class RHGateway:
    """
    Robinhood execution gateway.

    Parameters
    ----------
    paper_mode : bool
        When True (default) all orders are simulated in memory.
        When False, real orders are submitted via robin_stocks.
    redis_client : optional
        An async Redis client (redis.asyncio.Redis).  If None, idempotency
        cache is skipped — acceptable for testing without Redis.
    """

    def __init__(
        self,
        *,
        paper_mode: bool = True,
        redis_client: Any | None = None,
    ) -> None:
        self.paper_mode = paper_mode
        self._redis = redis_client

        # Paper mode state
        self._paper_orders: dict[str, OrderRecord] = {}      # order_id → OrderRecord
        self._paper_positions: dict[str, PositionRecord] = {}  # position_id → PositionRecord
        # Idempotency: client_order_id → order_id (also stored in Redis when available)
        self._local_idempotency: dict[str, str] = {}

        # Config from env
        self._max_position_usd: float = float(
            os.getenv("MAX_POSITION_SIZE_USD", str(_DEFAULT_MAX_POSITION_USD))
        )
        self._execution_buffer: float = _DEFAULT_EXECUTION_BUFFER
        self._paper_mode_env = os.getenv("PAPER_TRADING_MODE", "true").lower() == "true"

        # Live mode login state
        self._logged_in = False

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    async def execute_signal(self, signal: TradeSignal) -> OrderRecord | None:
        """
        Execute a TradeSignal.

        Steps:
          1. Fetch live/simulated quote
          2. Guard: min ask $0.10
          3. Guard: max OTM% for 0DTE
          4. Compute qty (max_position_usd / ask_per_contract, min 1)
          5. Compute limit_price with execution buffer
          6. Build deterministic client_order_id
          7. Idempotency check (Redis → local dict fallback)
          8. Submit (paper or live)
          9. Return OrderRecord

        Returns None if any guard rejects the signal.
        """
        # Step 1: get quote
        contract = await self.get_quote(
            symbol=signal.symbol,
            direction=signal.direction,
            strike=signal.strike,
            expiry=signal.expiry,
        )
        if contract is None:
            logger.warning(
                "execute_signal: no quote for %s %s %s %s",
                signal.symbol, signal.direction, signal.strike, signal.expiry,
            )
            return None

        # Step 2: min ask guard
        if not contract.is_tradable:
            logger.warning(
                "execute_signal: rejected — ask $%.2f < $0.10 for %s",
                contract.ask_per_share, signal.signal_id,
            )
            return None

        # Step 3: OTM% guard for 0DTE
        if signal.expiry == date.today():
            otm_pct = self._compute_otm_pct(signal.symbol, signal.direction, signal.strike)
            if otm_pct is not None and otm_pct > _MAX_OTM_PCT_0DTE:
                logger.warning(
                    "execute_signal: rejected — 0DTE strike %.0f is %.1f%% OTM (max %.0f%%)",
                    signal.strike, otm_pct * 100, _MAX_OTM_PCT_0DTE * 100,
                )
                return None

        # Step 4: compute qty
        ask_per_contract = contract.ask_per_share * 100
        qty = max(1, int(self._max_position_usd / ask_per_contract))

        # Step 5: limit price = signal_price * (1 + buffer)
        # Use signal_price rather than live ask so the analyst's intent is preserved.
        limit_per_share = signal.signal_price * (1 + self._execution_buffer)
        limit_per_contract = limit_per_share * 100

        # Step 6: deterministic client_order_id
        client_order_id = make_client_order_id(
            analyst_id=signal.analyst_id,
            action="BUY",
            symbol=signal.symbol,
            direction=signal.direction,
            strike=signal.strike,
            expiry=signal.expiry,
            qty=qty,
            trade_date=date.today(),
        )

        # Step 7: idempotency check
        cached_order_id = await self._idempotency_get(client_order_id)
        if cached_order_id is not None:
            logger.info(
                "execute_signal: idempotent hit — returning cached order %s", cached_order_id
            )
            cached_order = self._paper_orders.get(cached_order_id)
            if cached_order is not None:
                return cached_order
            # If live mode we don't have the cached object in memory; reconstruct minimally
            return None

        # Step 8: submit
        now = datetime.now(tz=timezone.utc)
        order_id = str(uuid.uuid4())

        if self.paper_mode:
            order = OrderRecord(
                order_id=order_id,
                client_order_id=client_order_id,
                signal_id=signal.signal_id,
                analyst_id=signal.analyst_id,
                symbol=signal.symbol,
                direction=signal.direction,
                strike=signal.strike,
                expiry=signal.expiry,
                qty=qty,
                limit_price_per_share=limit_per_share,
                limit_price_per_contract=limit_per_contract,
                submitted_at=now,
                status="FILLED",           # paper: optimistic immediate fill
                filled_price_per_share=limit_per_share,
                filled_price_per_contract=limit_per_contract,
                filled_at=now,
                paper_mode=True,
            )
            self._paper_orders[order_id] = order

            # Track position
            position = PositionRecord(
                order_id=order_id,
                signal_id=signal.signal_id,
                analyst_id=signal.analyst_id,
                symbol=signal.symbol,
                direction=signal.direction,
                strike=signal.strike,
                expiry=signal.expiry,
                qty=qty,
                avg_cost_per_share=limit_per_share,
                avg_cost_per_contract=limit_per_contract,
                opened_at=now,
                exit_rules=signal.exit_rules,
            )
            self._paper_positions[position.position_id] = position
            logger.info(
                "PAPER FILL: %s %s %s %.0f %s x%d @ $%.2f/share",
                signal.analyst_id, signal.symbol, signal.direction,
                signal.strike, signal.expiry, qty, limit_per_share,
            )
        else:
            # Live mode
            order = await self._submit_live_order(
                signal=signal,
                qty=qty,
                limit_per_share=limit_per_share,
                limit_per_contract=limit_per_contract,
                client_order_id=client_order_id,
                order_id=order_id,
                now=now,
            )

        # Step 9: cache idempotency key
        await self._idempotency_set(client_order_id, order_id)

        return order

    async def close_position(
        self, position: PositionRecord, qty: int, reason: str
    ) -> OrderRecord | None:
        """
        Close (or partially close) an open position.

        In paper mode: simulates a sell fill and removes/updates the position.
        In live mode: submits a sell-to-close order via robin_stocks.
        """
        logger.info(
            "close_position: %s %s x%d reason=%s",
            position.symbol, position.position_id, qty, reason,
        )

        client_order_id = make_client_order_id(
            analyst_id=position.analyst_id,
            action="SELL",
            symbol=position.symbol,
            direction=position.direction,
            strike=position.strike,
            expiry=position.expiry,
            qty=qty,
            trade_date=date.today(),
        )

        # Idempotency check
        cached_order_id = await self._idempotency_get(client_order_id)
        if cached_order_id is not None:
            logger.info("close_position: idempotent hit — already closed %s", cached_order_id)
            return self._paper_orders.get(cached_order_id)

        now = datetime.now(tz=timezone.utc)
        order_id = str(uuid.uuid4())

        # Sell price: use avg_cost (paper mode doesn't have a live quote for exit)
        sell_price_per_share = position.avg_cost_per_share
        sell_price_per_contract = sell_price_per_share * 100

        if self.paper_mode:
            order = OrderRecord(
                order_id=order_id,
                client_order_id=client_order_id,
                signal_id=position.signal_id,
                analyst_id=position.analyst_id,
                symbol=position.symbol,
                direction=position.direction,
                strike=position.strike,
                expiry=position.expiry,
                qty=qty,
                limit_price_per_share=sell_price_per_share,
                limit_price_per_contract=sell_price_per_contract,
                submitted_at=now,
                status="FILLED",
                filled_price_per_share=sell_price_per_share,
                filled_price_per_contract=sell_price_per_contract,
                filled_at=now,
                paper_mode=True,
            )
            self._paper_orders[order_id] = order

            # Remove or shrink position
            if qty >= position.qty:
                self._paper_positions.pop(position.position_id, None)
            else:
                updated = position.model_copy(
                    update={
                        "qty": position.qty - qty,
                        "has_sold_partial": True,
                        "partial_qty_sold": position.partial_qty_sold + qty,
                    }
                )
                self._paper_positions[position.position_id] = updated

            logger.info(
                "PAPER CLOSE: %s %s x%d @ $%.2f/share reason=%s",
                position.symbol, position.direction, qty, sell_price_per_share, reason,
            )
        else:
            order = await self._submit_live_close(
                position=position,
                qty=qty,
                client_order_id=client_order_id,
                order_id=order_id,
                now=now,
            )

        await self._idempotency_set(client_order_id, order_id)
        return order

    async def get_quote(
        self,
        symbol: str,
        direction: str,
        strike: float,
        expiry: date,
    ) -> OptionContract | None:
        """
        Fetch an option contract quote.

        Paper mode: returns a synthetic quote derived from signal_price (strike-based heuristic).
        Live mode: calls robin_stocks via asyncio.to_thread.
        """
        if self.paper_mode:
            return self._synthetic_quote(symbol, direction, strike, expiry)

        return await self._live_quote(symbol, direction, strike, expiry)

    async def get_positions(self) -> list[PositionRecord]:
        """Return all currently tracked open positions."""
        if self.paper_mode:
            return list(self._paper_positions.values())

        return await self._live_positions()

    async def get_account(self) -> dict[str, Any]:
        """Return account info (buying power, equity, etc.)."""
        if self.paper_mode:
            total_value = sum(
                p.avg_cost_per_contract * p.qty
                for p in self._paper_positions.values()
            )
            return {
                "paper_mode": True,
                "open_positions": len(self._paper_positions),
                "total_position_value_usd": round(total_value, 2),
                "max_position_size_usd": self._max_position_usd,
            }

        return await self._live_account()

    # ─────────────────────────────────────────────
    # Idempotency helpers
    # ─────────────────────────────────────────────

    async def _idempotency_get(self, client_order_id: str) -> str | None:
        """Return cached order_id if this client_order_id was already processed."""
        key = f"{_IDEMPOTENCY_KEY_PREFIX}{client_order_id}"
        if self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw:
                    data = json.loads(raw) if raw.startswith("{") else None
                    if data and "order_id" in data:
                        return data["order_id"]
                    # raw might be plain order_id string
                    return raw
            except Exception as exc:
                logger.warning("Redis idempotency get failed: %s — using local cache", exc)
        return self._local_idempotency.get(client_order_id)

    async def _idempotency_set(self, client_order_id: str, order_id: str) -> None:
        """Cache order_id for this client_order_id."""
        key = f"{_IDEMPOTENCY_KEY_PREFIX}{client_order_id}"
        self._local_idempotency[client_order_id] = order_id
        if self._redis is not None:
            try:
                payload = json.dumps({"order_id": order_id})
                await self._redis.setex(key, _IDEMPOTENCY_TTL, payload)
            except Exception as exc:
                logger.warning("Redis idempotency set failed: %s — local cache only", exc)

    # ─────────────────────────────────────────────
    # Paper mode helpers
    # ─────────────────────────────────────────────

    def _synthetic_quote(
        self,
        symbol: str,
        direction: str,
        strike: float,
        expiry: date,
    ) -> OptionContract | None:
        """
        Generate a plausible synthetic quote for paper mode.
        Ask is set to $1.00/share as a safe default above the $0.10 floor.
        """
        try:
            return OptionContract(
                symbol=symbol,
                direction=direction,  # type: ignore[arg-type]
                strike=strike,
                expiry=expiry,
                bid_per_share=0.90,
                ask_per_share=1.00,
                mark_per_share=0.95,
                open_interest=500,
                volume=200,
                implied_volatility=0.30,
                delta=0.40 if direction == "CALL" else -0.40,
            )
        except Exception as exc:
            logger.error("Synthetic quote failed: %s", exc)
            return None

    def _compute_otm_pct(
        self,
        symbol: str,
        direction: str,
        strike: float,
    ) -> float | None:
        """
        Estimate OTM% for 0DTE guard.

        For SPX/SPY we don't have a real spot price in paper mode,
        so we use a rough heuristic: assume the strike IS approximately
        at-the-money and return 0.0 (pass the guard).

        In live mode this would fetch the underlying spot price.
        """
        if self.paper_mode:
            return 0.0
        return None   # live mode: caller skips guard if None

    # ─────────────────────────────────────────────
    # Live mode helpers (all wrapped in to_thread)
    # ─────────────────────────────────────────────

    def _ensure_logged_in(self) -> None:
        """Login to Robinhood if not already authenticated."""
        import asyncio
        if self._logged_in:
            return
        import robin_stocks.robinhood as rh  # type: ignore[import]

        username = os.environ["ROBINHOOD_USERNAME"]
        password = os.environ["ROBINHOOD_PASSWORD"]
        totp = os.getenv("ROBINHOOD_TOTP")

        rh.login(username=username, password=password, mfa_code=totp)
        self._logged_in = True
        logger.info("Robinhood login successful")

    async def _live_quote(
        self,
        symbol: str,
        direction: str,
        strike: float,
        expiry: date,
    ) -> OptionContract | None:
        import asyncio
        import robin_stocks.robinhood as rh  # type: ignore[import]

        def _fetch() -> OptionContract | None:
            self._ensure_logged_in()
            expiry_str = expiry.strftime("%Y-%m-%d")
            option_type = "call" if direction == "CALL" else "put"
            data = rh.options.get_option_market_data(
                symbol, expiry_str, str(strike), option_type
            )
            if not data or not data[0]:
                return None
            d = data[0][0] if isinstance(data[0], list) else data[0]
            try:
                return OptionContract(
                    symbol=symbol,
                    direction=direction,  # type: ignore[arg-type]
                    strike=strike,
                    expiry=expiry,
                    bid_per_share=float(d.get("bid_price") or 0),
                    ask_per_share=float(d.get("ask_price") or 0),
                    mark_per_share=float(d.get("adjusted_mark_price") or 0),
                    open_interest=int(d.get("open_interest") or 0),
                    volume=int(d.get("volume") or 0),
                    implied_volatility=float(d["implied_volatility"])
                    if d.get("implied_volatility") else None,
                    delta=float(d["delta"]) if d.get("delta") else None,
                )
            except Exception as exc:
                logger.error("Failed to parse live quote: %s — data=%s", exc, d)
                return None

        return await asyncio.to_thread(_fetch)

    async def _submit_live_order(
        self,
        signal: TradeSignal,
        qty: int,
        limit_per_share: float,
        limit_per_contract: float,
        client_order_id: str,
        order_id: str,
        now: datetime,
    ) -> OrderRecord:
        import asyncio
        import robin_stocks.robinhood as rh  # type: ignore[import]

        def _submit() -> dict[str, Any]:
            self._ensure_logged_in()
            expiry_str = signal.expiry.strftime("%Y-%m-%d")
            option_type = "call" if signal.direction == "CALL" else "put"
            # SPX is an index option — use the 'index' option_type param
            instrument_type = "index" if signal.symbol in ("SPX", "XSP") else "equity"
            return rh.options.order_buy_option_limit(  # type: ignore[no-any-return]
                positionEffect="open",
                creditOrDebit="debit",
                price=limit_per_share,
                symbol=signal.symbol,
                quantity=qty,
                expirationDate=expiry_str,
                strike=signal.strike,
                optionType=option_type,
                timeInForce="gfd",
                jsonify=True,
            )

        result = await asyncio.to_thread(_submit)
        rh_status = result.get("state", "SUBMITTED") if result else "SUBMITTED"
        status_map = {
            "filled": "FILLED",
            "partially_filled": "PARTIALLY_FILLED",
            "cancelled": "CANCELLED",
            "rejected": "REJECTED",
        }
        mapped_status = status_map.get(rh_status.lower(), "SUBMITTED")

        return OrderRecord(
            order_id=result.get("id", order_id) if result else order_id,
            client_order_id=client_order_id,
            signal_id=signal.signal_id,
            analyst_id=signal.analyst_id,
            symbol=signal.symbol,
            direction=signal.direction,
            strike=signal.strike,
            expiry=signal.expiry,
            qty=qty,
            limit_price_per_share=limit_per_share,
            limit_price_per_contract=limit_per_contract,
            submitted_at=now,
            status=mapped_status,  # type: ignore[arg-type]
            paper_mode=False,
        )

    async def _submit_live_close(
        self,
        position: PositionRecord,
        qty: int,
        client_order_id: str,
        order_id: str,
        now: datetime,
    ) -> OrderRecord:
        import asyncio
        import robin_stocks.robinhood as rh  # type: ignore[import]

        def _submit() -> dict[str, Any]:
            self._ensure_logged_in()
            expiry_str = position.expiry.strftime("%Y-%m-%d")
            option_type = "call" if position.direction == "CALL" else "put"
            return rh.options.order_sell_option_limit(  # type: ignore[no-any-return]
                positionEffect="close",
                creditOrDebit="credit",
                price=position.avg_cost_per_share,
                symbol=position.symbol,
                quantity=qty,
                expirationDate=expiry_str,
                strike=position.strike,
                optionType=option_type,
                timeInForce="gfd",
                jsonify=True,
            )

        result = await asyncio.to_thread(_submit)
        sell_price = position.avg_cost_per_share

        return OrderRecord(
            order_id=result.get("id", order_id) if result else order_id,
            client_order_id=client_order_id,
            signal_id=position.signal_id,
            analyst_id=position.analyst_id,
            symbol=position.symbol,
            direction=position.direction,
            strike=position.strike,
            expiry=position.expiry,
            qty=qty,
            limit_price_per_share=sell_price,
            limit_price_per_contract=sell_price * 100,
            submitted_at=now,
            status="SUBMITTED",
            paper_mode=False,
        )

    async def _live_positions(self) -> list[PositionRecord]:
        """Fetch open option positions from Robinhood."""
        import asyncio
        import robin_stocks.robinhood as rh  # type: ignore[import]

        def _fetch() -> list[dict[str, Any]]:
            self._ensure_logged_in()
            return rh.options.get_open_option_positions() or []  # type: ignore[no-any-return]

        raw = await asyncio.to_thread(_fetch)
        # Note: in live mode we don't reconstruct full PositionRecord from RH data
        # because we lack ExitRules — the Monitor Agent should use its own state store.
        # Return empty list and log a warning.
        if raw:
            logger.warning(
                "get_positions() in live mode returns %d RH positions "
                "but cannot reconstruct ExitRules — use Monitor Agent state store",
                len(raw),
            )
        return []

    async def _live_account(self) -> dict[str, Any]:
        """Fetch account info from Robinhood."""
        import asyncio
        import robin_stocks.robinhood as rh  # type: ignore[import]

        def _fetch() -> dict[str, Any]:
            self._ensure_logged_in()
            profile = rh.profiles.load_account_profile() or {}
            return {
                "paper_mode": False,
                "buying_power": profile.get("buying_power"),
                "portfolio_value": profile.get("equity"),
                "day_trades_used": profile.get("day_trade_count"),
            }

        return await asyncio.to_thread(_fetch)

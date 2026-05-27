"""
Paper trading broker adapter.
Simulates realistic order fills with slippage, latency, and partial fills.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from ..domain.models import (
    Order, OrderStatus, OrderType, OrderSide,
    Position, PositionStatus, AssetClass, now_utc,
)
from ..domain.exceptions import BrokerConnectionError, BrokerOrderError

logger = logging.getLogger(__name__)

# Slippage model constants
MARKET_SLIPPAGE_BPS = 5        # 0.05% average slippage for market orders
PARTIAL_FILL_PROBABILITY = 0.1  # 10% chance of partial fill
FILL_LATENCY_MS = (50, 300)     # Random latency range in ms


class PaperBroker:
    """
    Paper trading broker that simulates exchange behavior.
    Features:
    - Realistic slippage for market orders
    - Partial fill simulation
    - Configurable latency
    - In-memory order and position tracking
    """

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        slippage_bps: float = MARKET_SLIPPAGE_BPS,
        simulate_latency: bool = True,
    ) -> None:
        self._cash = initial_cash
        self._initial_cash = initial_cash
        self._slippage_bps = slippage_bps
        self._simulate_latency = simulate_latency
        self._connected = False
        # Internal state — keyed by our order_id (not broker id)
        self._orders: dict[str, Order] = {}
        # Positions keyed by symbol
        self._positions: dict[str, Position] = {}
        # Pending limit orders keyed by order_id
        self._pending_orders: dict[str, Order] = {}
        self._fill_history: list[dict[str, Any]] = []
        self._broker_name = "paper"
        # Track day P&L
        self._day_pnl: float = 0.0
        self._day_start_value: float = initial_cash

    async def connect(self) -> None:
        self._connected = True
        logger.info("Paper broker connected (cash=%.2f)", self._cash)

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("Paper broker disconnected")

    def _check_connected(self) -> None:
        if not self._connected:
            raise BrokerConnectionError("paper", "Broker not connected")

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """Apply realistic slippage: buys pay more, sells receive less."""
        slippage_factor = self._slippage_bps / 10_000.0
        noise = random.gauss(0, slippage_factor * 0.3)
        net_slippage = slippage_factor + noise
        if side == OrderSide.BUY:
            return price * (1 + net_slippage)
        else:
            return price * (1 - net_slippage)

    def _fill_order(self, order: Order, fill_price: float) -> Order:
        """Apply fill to an order object and update positions/cash."""
        symbol = order.symbol.upper()
        filled_qty = order.quantity
        commission = max(1.0, filled_qty * fill_price * 0.0001)

        if order.side == OrderSide.BUY:
            cost = fill_price * filled_qty + commission
            if cost > self._cash:
                # Reduce qty to available cash
                max_qty = max(0.0, (self._cash - commission) / fill_price)
                if max_qty <= 0.0:
                    order.status = OrderStatus.REJECTED
                    return order
                filled_qty = max_qty
                cost = fill_price * filled_qty + commission
            self._cash -= cost

            # Update or create position
            if symbol in self._positions and self._positions[symbol].status == PositionStatus.OPEN:
                pos = self._positions[symbol]
                total_qty = pos.quantity + filled_qty
                pos.avg_entry_price = (
                    pos.avg_entry_price * pos.quantity + fill_price * filled_qty
                ) / total_qty
                pos.quantity = total_qty
                pos.current_price = fill_price
            else:
                pos = Position(
                    symbol=symbol,
                    asset_class=order.asset_class,
                    side=OrderSide.BUY,
                    quantity=filled_qty,
                    avg_entry_price=fill_price,
                    current_price=fill_price,
                    status=PositionStatus.OPEN,
                )
                self._positions[symbol] = pos

        else:  # SELL
            if symbol in self._positions and self._positions[symbol].status == PositionStatus.OPEN:
                pos = self._positions[symbol]
                closed_qty = min(filled_qty, pos.quantity)
                realized_pnl = (fill_price - pos.avg_entry_price) * closed_qty
                self._cash += fill_price * closed_qty - commission
                self._day_pnl += realized_pnl
                pos.realized_pnl += realized_pnl
                pos.quantity -= closed_qty
                filled_qty = closed_qty
                if pos.quantity <= 0.001:
                    pos.status = PositionStatus.CLOSED
                    pos.closed_at = now_utc()
                    pos.quantity = 0.0
                pos.current_price = fill_price
            else:
                # Short sell (simplified — just credit cash)
                self._cash += fill_price * filled_qty - commission

        broker_order_id = f"paper-{uuid.uuid4().hex[:10]}"
        order.broker_order_id = broker_order_id
        order.filled_quantity = round(filled_qty, 6)
        order.average_fill_price = round(fill_price, 4)
        order.commission = round(commission, 4)
        order.status = OrderStatus.FILLED
        order.filled_at = now_utc()

        self._fill_history.append({
            "order_id": order.order_id,
            "broker_order_id": broker_order_id,
            "symbol": symbol,
            "side": order.side.value,
            "filled_qty": filled_qty,
            "fill_price": fill_price,
            "commission": commission,
            "filled_at": order.filled_at.isoformat() if order.filled_at else None,
        })
        return order

    async def submit_order(self, order: Order) -> dict[str, Any]:
        """Submit and immediately simulate a paper fill."""
        self._check_connected()

        # Simulate network latency
        if self._simulate_latency:
            latency_ms = random.uniform(*FILL_LATENCY_MS)
            await asyncio.sleep(latency_ms / 1000.0)

        self._orders[order.order_id] = order

        if order.order_type == OrderType.MARKET:
            # Market orders fill immediately at current price + slippage
            base_price = order.limit_price or order.stop_price or 100.0
            fill_price = self._apply_slippage(base_price, order.side)
            order = self._fill_order(order, fill_price)
            self._orders[order.order_id] = order
            logger.info(
                "Paper MARKET fill: %s %s %.4f @ $%.4f",
                order.side.value.upper(), order.symbol, order.filled_quantity, fill_price,
            )
        elif order.order_type == OrderType.LIMIT and order.limit_price:
            # Limit orders go into pending queue
            order.status = OrderStatus.SUBMITTED
            self._pending_orders[order.order_id] = order
            logger.info(
                "Paper LIMIT order queued: %s %s %.4f @ $%.4f",
                order.side.value.upper(), order.symbol, order.quantity, order.limit_price,
            )
        else:
            # Default: treat as market
            base_price = order.limit_price or order.stop_price or 100.0
            fill_price = self._apply_slippage(base_price, order.side)
            order = self._fill_order(order, fill_price)
            self._orders[order.order_id] = order

        return {
            "broker_order_id": order.broker_order_id or f"paper-pending-{order.order_id[:8]}",
            "status": order.status.value,
            "filled_quantity": order.filled_quantity,
            "average_fill_price": order.average_fill_price,
            "commission": order.commission,
            "is_partial": False,
            "remaining_quantity": order.remaining_quantity,
            "filled_at": order.filled_at.isoformat() if order.filled_at else None,
        }

    async def cancel_order(self, order_id: str) -> Order:
        """Remove from pending queue and mark as CANCELLED."""
        order = self._orders.get(order_id) or self._pending_orders.get(order_id)
        if order:
            order.status = OrderStatus.CANCELLED
            self._pending_orders.pop(order_id, None)
            self._orders[order_id] = order
            logger.info("Paper order cancelled: %s", order_id)
            return order
        raise BrokerOrderError("paper", order_id, "Order not found")

    async def get_order_status(self, order_id: str) -> Order:
        """Return order from internal tracking dict."""
        order = self._orders.get(order_id)
        if not order:
            raise BrokerOrderError("paper", order_id, "Order not found")
        return order

    async def process_pending_orders(self, current_prices: dict[str, float]) -> list[Order]:
        """
        For each pending limit order: check if fill conditions are met.
        BUY: fill if current_price <= limit_price
        SELL: fill if current_price >= limit_price
        Returns list of newly filled orders.
        """
        filled: list[Order] = []
        to_remove: list[str] = []

        for order_id, order in list(self._pending_orders.items()):
            symbol = order.symbol.upper()
            price = current_prices.get(symbol)
            if price is None or price <= 0:
                continue

            should_fill = False
            if order.side == OrderSide.BUY and order.limit_price and price <= order.limit_price:
                should_fill = True
            elif order.side == OrderSide.SELL and order.limit_price and price >= order.limit_price:
                should_fill = True

            if should_fill:
                fill_price = order.limit_price or price  # fills at limit price
                order = self._fill_order(order, fill_price)
                self._orders[order_id] = order
                to_remove.append(order_id)
                filled.append(order)
                logger.info(
                    "Pending LIMIT order filled: %s %s %.4f @ $%.4f",
                    order.side.value.upper(), order.symbol, order.filled_quantity, fill_price,
                )

        for order_id in to_remove:
            self._pending_orders.pop(order_id, None)

        return filled

    async def get_positions(self) -> list[Position]:
        """Return list of all open positions."""
        return [
            p for p in self._positions.values()
            if p.status == PositionStatus.OPEN and p.quantity > 0.001
        ]

    async def get_portfolio_summary(self) -> dict[str, Any]:
        """Return full portfolio summary."""
        open_positions = [
            p for p in self._positions.values()
            if p.status == PositionStatus.OPEN and p.quantity > 0.001
        ]
        total_market_value = sum(p.market_value for p in open_positions)
        unrealized_pnl = sum(p.unrealized_pnl for p in open_positions)
        total_value = self._cash + total_market_value

        return {
            "cash": round(self._cash, 2),
            "positions": [p.model_dump() for p in open_positions],
            "total_value": round(total_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "day_pnl": round(self._day_pnl, 2),
            "total_market_value": round(total_market_value, 2),
            "open_positions_count": len(open_positions),
        }

    async def get_account(self) -> dict[str, Any]:
        """Return paper account summary."""
        summary = await self.get_portfolio_summary()
        return {
            "status": "ACTIVE",
            "mode": "paper",
            "cash_balance": summary["cash"],
            "positions_value": summary["total_market_value"],
            "portfolio_value": summary["total_value"],
            "currency": "USD",
        }

    async def health_check(self) -> dict[str, Any]:
        open_positions = await self.get_positions()
        return {
            "status": "healthy",
            "broker": "paper",
            "connected": self._connected,
            "cash": round(self._cash, 2),
            "open_positions": len(open_positions),
        }


__all__ = ["PaperBroker"]

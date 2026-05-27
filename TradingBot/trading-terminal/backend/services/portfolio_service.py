"""
Portfolio service — position tracking, PnL calculation, portfolio management.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..domain.models import (
    Position, Portfolio, Order, OrderSide, PositionStatus, AssetClass, now_utc
)
from ..domain.events import PositionOpened, PositionClosed, PortfolioUpdated
from ..domain.exceptions import InsufficientFunds, PositionNotFound
from ..ports.outbound import IPositionRepository, IEventStore, IMessageBusPublisher
from ..adapters.kafka_publisher import KafkaTopics

logger = logging.getLogger(__name__)


class PortfolioService:
    """
    Manages positions and portfolio state.
    Called after every order fill to update positions and PnL.
    Also provides a get_summary/get_positions interface backed by PaperBroker
    when a broker instance is available.
    """

    def __init__(
        self,
        position_repo: IPositionRepository,
        event_store: IEventStore,
        publisher: IMessageBusPublisher,
        initial_cash: float = 100_000.0,
        broker: Any = None,
    ) -> None:
        self._position_repo = position_repo
        self._event_store = event_store
        self._publisher = publisher
        self._cash = initial_cash
        self._realized_pnl = 0.0
        self._broker = broker

    async def get_summary(self) -> dict[str, Any]:
        """Get portfolio summary — delegates to broker when available."""
        if self._broker:
            try:
                positions = await self._broker.get_positions()
                summary = await self._broker.get_portfolio_summary()
                return {
                    "cash": summary.get("cash", self._cash),
                    "total_value": summary.get("total_value", self._cash),
                    "unrealized_pnl": summary.get("unrealized_pnl", 0.0),
                    "day_pnl": summary.get("day_pnl", 0.0),
                    "positions": [p.model_dump() for p in positions],
                    "position_count": len(positions),
                }
            except Exception as e:
                logger.warning("Broker get_summary failed, falling back to DB: %s", e)
        return await self.get_portfolio_snapshot()

    async def get_positions(self) -> list[Position]:
        """Return open positions — delegates to broker when available."""
        if self._broker:
            try:
                return await self._broker.get_positions()
            except Exception as e:
                logger.warning("Broker get_positions failed, falling back to DB: %s", e)
        return await self._position_repo.list_open_positions()

    async def get_equity_curve(self, range: str = "1D") -> list[dict[str, Any]]:
        """
        Return equity curve data points [{timestamp, nav}].
        Queries order_events for fill events and computes running NAV.
        """
        try:
            events = await self._event_store.get_recent_events(
                limit=200, event_type="OrderFilled"
            )
            nav = self._cash
            curve: list[dict[str, Any]] = []
            for evt in reversed(events):
                payload = evt.get("payload", {})
                if isinstance(payload, str):
                    import json
                    payload = json.loads(payload)
                ts = evt.get("timestamp") or evt.get("created_at")
                curve.append({
                    "timestamp": str(ts),
                    "nav": round(nav, 2),
                })
            # Always include current NAV
            summary = await self.get_summary()
            curve.append({
                "timestamp": now_utc().isoformat(),
                "nav": round(summary.get("total_value", nav), 2),
            })
            return curve
        except Exception as e:
            logger.warning("get_equity_curve failed: %s", e)
            return [{"timestamp": now_utc().isoformat(), "nav": round(self._cash, 2)}]

    async def process_fill(
        self,
        order: Order,
        fill_price: float,
        filled_quantity: float,
    ) -> Position:
        """
        Update portfolio state after an order fill.
        Opens new positions or updates/closes existing ones.
        """
        symbol = order.symbol.upper()
        existing = await self._position_repo.get_position_by_symbol(symbol)

        if order.side == OrderSide.BUY:
            return await self._process_buy(order, symbol, fill_price, filled_quantity, existing)
        else:
            return await self._process_sell(order, symbol, fill_price, filled_quantity, existing)

    async def _process_buy(
        self,
        order: Order,
        symbol: str,
        fill_price: float,
        qty: float,
        existing: Position | None,
    ) -> Position:
        if existing and existing.status == PositionStatus.OPEN:
            old_qty = existing.quantity
            old_cost = existing.avg_entry_price
            new_total = old_qty + qty
            existing.avg_entry_price = (old_cost * old_qty + fill_price * qty) / new_total
            existing.quantity = new_total
            existing.current_price = fill_price
            position = await self._position_repo.update_position(existing)
            logger.info(
                "Added to position [%s]: %s qty=%.4f avg_entry=%.4f",
                position.position_id, symbol, new_total, existing.avg_entry_price,
            )
        else:
            position = Position(
                symbol=symbol,
                asset_class=order.asset_class,
                side=OrderSide.BUY,
                quantity=qty,
                avg_entry_price=fill_price,
                current_price=fill_price,
            )
            position = await self._position_repo.save_position(position)

            event = PositionOpened(
                aggregate_id=position.position_id,
                symbol=symbol,
                side=OrderSide.BUY,
                quantity=qty,
                entry_price=fill_price,
                order_id=order.order_id,
            )
            try:
                await self._event_store.append(event)
                await self._publisher.publish(KafkaTopics.PORTFOLIO_UPDATES, event)
            except Exception as e:
                logger.warning("Event publish failed (non-fatal): %s", e)
            logger.info(
                "Position opened [%s]: LONG %s %.4f @ $%.4f",
                position.position_id, symbol, qty, fill_price,
            )

        self._cash -= fill_price * qty + order.commission
        await self._publish_portfolio_update()
        return position

    async def _process_sell(
        self,
        order: Order,
        symbol: str,
        fill_price: float,
        qty: float,
        existing: Position | None,
    ) -> Position:
        if not existing:
            logger.warning(
                "Selling %s but no open position found — treating as short open", symbol
            )
            position = Position(
                symbol=symbol,
                asset_class=order.asset_class,
                side=OrderSide.SELL,
                quantity=qty,
                avg_entry_price=fill_price,
                current_price=fill_price,
            )
            return await self._position_repo.save_position(position)

        closed_qty = min(qty, existing.quantity)
        realized_pnl = (fill_price - existing.avg_entry_price) * closed_qty
        self._realized_pnl += realized_pnl
        self._cash += fill_price * closed_qty - order.commission

        if abs(existing.quantity - closed_qty) < 0.001:
            existing.status = PositionStatus.CLOSED
            existing.quantity = 0.0
            existing.realized_pnl += realized_pnl
            existing.closed_at = now_utc()
            position = await self._position_repo.update_position(existing)

            close_event = PositionClosed(
                aggregate_id=existing.position_id,
                symbol=symbol,
                closed_quantity=closed_qty,
                exit_price=fill_price,
                realized_pnl=round(realized_pnl, 4),
                hold_duration_seconds=(now_utc() - existing.opened_at).total_seconds(),
                order_id=order.order_id,
            )
            try:
                await self._event_store.append(close_event)
                await self._publisher.publish(KafkaTopics.PORTFOLIO_UPDATES, close_event)
            except Exception as e:
                logger.warning("Event publish failed (non-fatal): %s", e)
            logger.info(
                "Position CLOSED [%s]: %s realized_pnl=$%.2f",
                existing.position_id, symbol, realized_pnl,
            )
        else:
            existing.quantity -= closed_qty
            existing.realized_pnl += realized_pnl
            existing.current_price = fill_price
            position = await self._position_repo.update_position(existing)
            logger.info(
                "Position PARTIALLY closed [%s]: %s sold=%.4f realized_pnl=$%.2f remaining=%.4f",
                existing.position_id, symbol, closed_qty, realized_pnl, existing.quantity,
            )

        await self._publish_portfolio_update()
        return position

    async def get_portfolio_snapshot(self) -> dict[str, Any]:
        """Build a complete portfolio snapshot with per-position detail."""
        open_positions = await self._position_repo.list_open_positions()
        total_market_value = sum(p.market_value for p in open_positions)
        total_unrealized = sum(p.unrealized_pnl for p in open_positions)

        return {
            "cash_balance": round(self._cash, 2),
            "total_market_value": round(total_market_value, 2),
            "total_equity": round(self._cash + total_market_value, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "realized_pnl": round(self._realized_pnl, 2),
            "total_pnl": round(total_unrealized + self._realized_pnl, 2),
            "open_positions_count": len(open_positions),
            "positions": [
                {
                    "symbol": p.symbol,
                    "qty": p.quantity,
                    "entry": p.avg_entry_price,
                    "current": p.current_price,
                    "unrealized_pnl": round(p.unrealized_pnl, 2),
                    "return_pct": round(p.return_pct, 2),
                    "market_value": round(p.market_value, 2),
                }
                for p in open_positions
            ],
        }

    async def update_prices(self, price_updates: dict[str, float]) -> None:
        """Batch-update current prices for all open positions."""
        open_positions = await self._position_repo.list_open_positions()
        for pos in open_positions:
            if pos.symbol in price_updates:
                pos.current_price = price_updates[pos.symbol]
                await self._position_repo.update_position(pos)

    async def _publish_portfolio_update(self) -> None:
        open_positions = await self._position_repo.list_open_positions()
        total_market_value = sum(p.market_value for p in open_positions)
        total_unrealized = sum(p.unrealized_pnl for p in open_positions)

        event = PortfolioUpdated(
            aggregate_id="portfolio-default",
            cash_balance=round(self._cash, 2),
            total_equity=round(self._cash + total_market_value, 2),
            total_market_value=round(total_market_value, 2),
            unrealized_pnl=round(total_unrealized, 2),
            realized_pnl=round(self._realized_pnl, 2),
            open_positions_count=len(open_positions),
            position_symbols=[p.symbol for p in open_positions],
        )
        try:
            await self._publisher.publish(KafkaTopics.PORTFOLIO_UPDATES, event)
        except Exception as e:
            logger.warning("Portfolio event publish failed (non-fatal): %s", e)


__all__ = ["PortfolioService"]

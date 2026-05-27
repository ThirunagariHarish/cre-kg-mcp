"""
Order gateway service — creates and manages order lifecycle.
Sits between risk approval and execution service.
"""
from __future__ import annotations

import logging
from typing import Any

from ..domain.models import Order, OrderStatus, OrderType, OrderSide, AssetClass, now_utc
from ..domain.events import OrderCreated, OrderCancelled
from ..domain.exceptions import OrderNotFound, InvalidOrderState
from ..ports.outbound import IOrderRepository, IEventStore, IMessageBusPublisher
from ..adapters.kafka_publisher import KafkaTopics

logger = logging.getLogger(__name__)


class OrderGatewayService:
    """
    Creates orders from risk-approved signals and manages their lifecycle.
    Publishes OrderCreated events to trigger execution.
    """

    def __init__(
        self,
        order_repo: IOrderRepository,
        event_store: IEventStore,
        publisher: IMessageBusPublisher,
    ) -> None:
        self._order_repo = order_repo
        self._event_store = event_store
        self._publisher = publisher

    async def create_order_from_signal(
        self,
        signal_id: str,
        symbol: str,
        side: OrderSide,
        quantity: float,
        entry_price: float | None = None,
        stop_price: float | None = None,
        order_type: OrderType = OrderType.MARKET,
        time_in_force: str = "day",
        asset_class: AssetClass = AssetClass.EQUITY,
        metadata: dict[str, Any] | None = None,
    ) -> Order:
        """
        Create an order from a risk-approved signal.
        Limit price is only set when order type is LIMIT; market orders carry no price.
        """
        order = Order(
            signal_id=signal_id,
            symbol=symbol.upper(),
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=entry_price if order_type == OrderType.LIMIT else None,
            stop_price=stop_price,
            time_in_force=time_in_force,
            asset_class=asset_class,
            metadata=metadata or {},
        )

        # Persist order first — event store is the source of truth
        order = await self._order_repo.save_order(order)

        # Publish domain event to event store + Kafka
        event = OrderCreated(
            aggregate_id=order.order_id,
            signal_id=signal_id,
            symbol=symbol.upper(),
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=order.limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            asset_class=asset_class,
        )
        await self._event_store.append(event)
        await self._publisher.publish(KafkaTopics.ORDERS, event)

        logger.info(
            "Order created [%s]: %s %s %.4f @ %s",
            order.order_id, side.value.upper(), symbol, quantity,
            entry_price or "MARKET",
        )
        return order

    async def cancel_order(self, order_id: str, reason: str = "user_requested") -> Order:
        """
        Cancel an order if it is in a cancellable state.
        Raises OrderNotFound or InvalidOrderState on bad transitions.
        """
        order = await self._order_repo.get_order(order_id)
        if not order:
            raise OrderNotFound(order_id)

        cancellable_states = {OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}
        if order.status not in cancellable_states:
            raise InvalidOrderState(order_id, order.status.value, "pending/submitted/partial")

        order.status = OrderStatus.CANCELLED
        order = await self._order_repo.update_order(order)

        event = OrderCancelled(
            aggregate_id=order_id,
            reason=reason,
        )
        await self._event_store.append(event)

        logger.info("Order cancelled [%s]: %s", order_id, reason)
        return order

    async def get_order(self, order_id: str) -> Order | None:
        return await self._order_repo.get_order(order_id)

    async def list_orders(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Order]:
        return await self._order_repo.list_orders(status=status, limit=limit)

    async def get_open_orders(self) -> list[Order]:
        """Return all orders that are pending, submitted, or partially filled."""
        open_statuses = [
            OrderStatus.PENDING.value,
            OrderStatus.SUBMITTED.value,
            OrderStatus.PARTIALLY_FILLED.value,
        ]
        results: list[Order] = []
        for status in open_statuses:
            results.extend(await self._order_repo.list_orders(status=status, limit=200))
        return results


__all__ = ["OrderGatewayService"]

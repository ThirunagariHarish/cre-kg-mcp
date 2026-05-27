"""
Execution service — sends orders to brokers and processes fills.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..domain.models import Order, Position, OrderStatus, RiskDecision, RiskDecisionStatus, now_utc
from ..domain.events import OrderSubmitted, OrderFilled, OrderRejected
from ..domain.exceptions import OrderNotFound, BrokerOrderError
from ..ports.outbound import IOrderRepository, IBrokerAdapter, IEventStore, IMessageBusPublisher
from ..adapters.kafka_publisher import KafkaTopics

logger = logging.getLogger(__name__)


class ExecutionService:
    """
    Coordinates order submission to brokers and processes fill callbacks.
    Supports multiple broker adapters (paper, alpaca, etc).
    """

    def __init__(
        self,
        order_repo: IOrderRepository,
        broker: IBrokerAdapter,
        event_store: IEventStore,
        publisher: IMessageBusPublisher,
        broker_name: str = "paper",
        redis: Any = None,
    ) -> None:
        self._order_repo = order_repo
        self._broker = broker
        self._event_store = event_store
        self._publisher = publisher
        self._broker_name = broker_name
        self._redis = redis

    async def _redis_broadcast(self, event_type: str, data: Any) -> None:
        """Publish to Redis pub/sub ws:events channel (non-fatal)."""
        if not self._redis:
            return
        try:
            message = {
                "type": event_type,
                "data": data,
                "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
            }
            await self._redis.publish("ws:events", json.dumps(message, default=str))
        except Exception as e:
            logger.warning("Redis broadcast failed (non-fatal): %s", e)

    async def execute_order(self, order: Order, current_price: float | None = None) -> Order:
        """
        Submit an order to the broker adapter and process the result.
        Updates order status and publishes fill events.
        On broker failure the order is marked REJECTED and the error is recorded.
        """
        order.status = OrderStatus.SUBMITTED
        order.submitted_at = now_utc()

        # If current_price provided and no limit_price set, use it
        if current_price and not order.limit_price:
            order.limit_price = current_price

        order = await self._order_repo.update_order(order)

        try:
            fill_result = await self._broker.submit_order(order)
        except Exception as exc:
            logger.error("Broker submission failed for %s: %s", order.order_id, exc)
            order.status = OrderStatus.REJECTED
            order = await self._order_repo.update_order(order)

            rejected_event = OrderRejected(
                aggregate_id=order.order_id,
                reason=str(exc),
            )
            try:
                await self._event_store.append(rejected_event)
                await self._publisher.publish(KafkaTopics.ORDERS, rejected_event)
            except Exception as e:
                logger.warning("Event publish failed (non-fatal): %s", e)

            await self._redis_broadcast("ORDER_UPDATE", order.model_dump())
            return order

        broker_order_id = fill_result.get("broker_order_id", "")
        status = fill_result.get("status", "unknown")
        filled_qty = float(fill_result.get("filled_quantity", 0))
        fill_price = float(fill_result.get("average_fill_price", 0))
        commission = float(fill_result.get("commission", 0))
        is_partial = fill_result.get("is_partial", False)

        # Emit submitted event
        submitted_event = OrderSubmitted(
            aggregate_id=order.order_id,
            broker_order_id=broker_order_id,
            broker_name=self._broker_name,
        )
        try:
            await self._event_store.append(submitted_event)
        except Exception as e:
            logger.warning("Event store append failed (non-fatal): %s", e)

        # Apply fill data to the order entity
        order.broker_order_id = broker_order_id
        order.filled_quantity = filled_qty
        order.average_fill_price = fill_price if fill_price > 0 else None
        order.commission = commission
        order.status = OrderStatus.PARTIALLY_FILLED if is_partial else OrderStatus.FILLED
        if not is_partial and filled_qty > 0:
            order.filled_at = now_utc()
        order = await self._order_repo.update_order(order)

        # Publish fill event
        if filled_qty > 0:
            fill_event = OrderFilled(
                aggregate_id=order.order_id,
                broker_order_id=broker_order_id,
                filled_quantity=filled_qty,
                average_fill_price=fill_price,
                commission=commission,
                is_partial=is_partial,
            )
            try:
                await self._event_store.append(fill_event)
                await self._publisher.publish(KafkaTopics.ORDER_FILLS, fill_event)
            except Exception as e:
                logger.warning("Event publish failed (non-fatal): %s", e)

        # Broadcast to WebSocket via Redis
        await self._redis_broadcast("ORDER_UPDATE", order.model_dump())

        logger.info(
            "Order %s [%s]: filled %.4f @ $%.4f (status=%s, broker=%s)",
            "PARTIALLY" if is_partial else "FULLY",
            order.order_id, filled_qty, fill_price, order.status.value, self._broker_name,
        )
        return order

    async def submit_and_execute(
        self,
        order: Order,
        risk_decision: RiskDecision,
        current_price: float | None = None,
    ) -> Order:
        """Only execute if risk approved."""
        if risk_decision.status != RiskDecisionStatus.APPROVED:
            order.status = OrderStatus.REJECTED
            try:
                await self._order_repo.save_order(order)
            except Exception as e:
                logger.warning("Failed to save rejected order: %s", e)
            await self._redis_broadcast("ORDER_UPDATE", order.model_dump())
            return order
        return await self.execute_order(order, current_price)

    async def process_fill_callback(
        self,
        broker_order_id: str,
        filled_qty: float,
        fill_price: float,
        commission: float = 0.0,
    ) -> Order | None:
        """
        Process an asynchronous fill callback from the broker.
        Returns None when the broker_order_id is not recognized.
        """
        order = await self._order_repo.get_order_by_broker_id(broker_order_id)
        if not order:
            logger.warning("Fill callback for unknown broker order: %s", broker_order_id)
            return None

        order.filled_quantity = filled_qty
        order.average_fill_price = fill_price
        order.commission = commission
        is_partial = filled_qty < order.quantity
        order.status = OrderStatus.PARTIALLY_FILLED if is_partial else OrderStatus.FILLED
        if not is_partial:
            order.filled_at = now_utc()
        order = await self._order_repo.update_order(order)

        fill_event = OrderFilled(
            aggregate_id=order.order_id,
            broker_order_id=broker_order_id,
            filled_quantity=filled_qty,
            average_fill_price=fill_price,
            commission=commission,
            is_partial=is_partial,
        )
        try:
            await self._event_store.append(fill_event)
            await self._publisher.publish(KafkaTopics.ORDER_FILLS, fill_event)
        except Exception as e:
            logger.warning("Event publish failed (non-fatal): %s", e)

        await self._redis_broadcast("ORDER_UPDATE", order.model_dump())

        logger.info(
            "Fill callback processed: broker_order=%s filled=%.4f @ $%.4f",
            broker_order_id, filled_qty, fill_price,
        )
        return order


__all__ = ["ExecutionService"]

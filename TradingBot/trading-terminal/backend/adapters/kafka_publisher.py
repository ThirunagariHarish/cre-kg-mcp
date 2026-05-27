"""
Kafka message bus adapter.
Implements IMessageBusPublisher using confluent-kafka.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..domain.events import DomainEvent
from ..ports.outbound import IMessageBusPublisher

logger = logging.getLogger(__name__)


class KafkaPublisher:
    """Confluent-Kafka based event publisher."""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        client_id: str = "trading-terminal-producer",
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._producer: Any = None

    async def start(self) -> None:
        """Initialize Kafka producer."""
        try:
            from confluent_kafka import Producer  # type: ignore

            self._producer = Producer(
                {
                    "bootstrap.servers": self._bootstrap_servers,
                    "client.id": self._client_id,
                    "acks": "all",
                    "retries": 3,
                    "retry.backoff.ms": 100,
                    "compression.type": "snappy",
                    "linger.ms": 5,
                    "batch.size": 16384,
                }
            )
            logger.info("Kafka producer initialized: %s", self._bootstrap_servers)
        except ImportError:
            logger.warning("confluent-kafka not installed, using no-op publisher")
            self._producer = None
        except Exception as exc:
            logger.error("Failed to initialize Kafka producer: %s", exc)
            raise

    async def stop(self) -> None:
        """Flush and close producer."""
        if self._producer:
            self._producer.flush(timeout=10)
            logger.info("Kafka producer flushed and closed")

    def _delivery_report(self, err: Any, msg: Any) -> None:
        if err:
            logger.error("Kafka delivery failed: %s", err)
        else:
            logger.debug("Delivered to %s [%d]", msg.topic(), msg.partition())

    async def publish(self, topic: str, event: DomainEvent) -> None:
        """Publish a domain event to a Kafka topic."""
        payload = event.to_kafka_payload()
        await self.publish_raw(topic, payload)

    async def publish_raw(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish a raw dict payload to a Kafka topic."""
        if not self._producer:
            logger.debug("Kafka unavailable, dropping event to %s: %s", topic, payload.get("event_type"))
            return

        try:
            serialized = json.dumps(payload, default=str).encode("utf-8")
            self._producer.produce(
                topic=topic,
                value=serialized,
                key=payload.get("aggregate_id", "").encode("utf-8"),
                callback=self._delivery_report,
            )
            self._producer.poll(0)
        except Exception as exc:
            logger.error("Failed to publish to %s: %s", topic, exc)
            raise


# Kafka topic constants
class KafkaTopics:
    RAW_MESSAGES = "raw-messages"
    PARSED_IDEAS = "parsed-ideas"
    ENRICHED_SIGNALS = "enriched-signals"
    TRADE_SIGNALS = "trade-signals"
    RISK_DECISIONS = "risk-decisions"
    ORDERS = "orders"
    ORDER_FILLS = "order-fills"
    PORTFOLIO_UPDATES = "portfolio-updates"
    AUDIT_EVENTS = "audit-events"
    NOTIFICATIONS = "notifications"


__all__ = ["KafkaPublisher", "KafkaTopics"]

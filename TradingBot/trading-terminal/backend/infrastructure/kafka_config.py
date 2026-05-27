"""
Kafka producer and consumer configuration.
Topic definitions and partition strategies.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# ─── Topic Configurations ───

TOPIC_CONFIGS: dict[str, dict[str, Any]] = {
    "raw-messages": {
        "partitions": 3,
        "replication_factor": 1,
        "retention_ms": 604_800_000,  # 7 days
        "cleanup_policy": "delete",
    },
    "parsed-ideas": {
        "partitions": 3,
        "replication_factor": 1,
        "retention_ms": 604_800_000,
        "cleanup_policy": "delete",
    },
    "enriched-signals": {
        "partitions": 3,
        "replication_factor": 1,
        "retention_ms": 604_800_000,
        "cleanup_policy": "delete",
    },
    "trade-signals": {
        "partitions": 3,
        "replication_factor": 1,
        "retention_ms": 2_592_000_000,  # 30 days
        "cleanup_policy": "delete",
    },
    "risk-decisions": {
        "partitions": 1,
        "replication_factor": 1,
        "retention_ms": 2_592_000_000,
        "cleanup_policy": "delete",
    },
    "orders": {
        "partitions": 3,
        "replication_factor": 1,
        "retention_ms": 2_592_000_000,
        "cleanup_policy": "delete",
    },
    "order-fills": {
        "partitions": 3,
        "replication_factor": 1,
        "retention_ms": 2_592_000_000,
        "cleanup_policy": "delete",
    },
    "portfolio-updates": {
        "partitions": 1,
        "replication_factor": 1,
        "retention_ms": 86_400_000,  # 1 day
        "cleanup_policy": "delete",
    },
    "audit-events": {
        "partitions": 1,
        "replication_factor": 1,
        "retention_ms": 31_536_000_000,  # 1 year
        "cleanup_policy": "compact,delete",
    },
    "notifications": {
        "partitions": 1,
        "replication_factor": 1,
        "retention_ms": 86_400_000,
        "cleanup_policy": "delete",
    },
}


def get_producer_config(bootstrap_servers: str, client_id: str = "trading-terminal") -> dict[str, Any]:
    return {
        "bootstrap.servers": bootstrap_servers,
        "client.id": client_id,
        "acks": "all",
        "retries": 5,
        "retry.backoff.ms": 200,
        "max.in.flight.requests.per.connection": 5,
        "enable.idempotence": True,
        "compression.type": "snappy",
        "linger.ms": 5,
        "batch.size": 32768,
        "buffer.memory": 33554432,
    }


def get_consumer_config(
    bootstrap_servers: str,
    group_id: str,
    auto_offset_reset: str = "latest",
) -> dict[str, Any]:
    return {
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,
        "auto.offset.reset": auto_offset_reset,
        "enable.auto.commit": True,
        "auto.commit.interval.ms": 5000,
        "max.poll.interval.ms": 300000,
        "session.timeout.ms": 30000,
        "fetch.min.bytes": 1,
        "fetch.max.wait.ms": 500,
    }


async def create_topics(bootstrap_servers: str) -> None:
    """Create all required Kafka topics if they don't exist."""
    try:
        from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore

        admin = AdminClient({"bootstrap.servers": bootstrap_servers})
        new_topics = [
            NewTopic(
                name,
                num_partitions=cfg["partitions"],
                replication_factor=cfg["replication_factor"],
                config={
                    "retention.ms": str(cfg["retention_ms"]),
                    "cleanup.policy": cfg["cleanup_policy"],
                },
            )
            for name, cfg in TOPIC_CONFIGS.items()
        ]
        results = admin.create_topics(new_topics)
        for topic, future in results.items():
            try:
                future.result(timeout=5)  # don't block forever if Kafka is down
                logger.info("Kafka topic created: %s", topic)
            except Exception as exc:
                if "already exists" in str(exc).lower() or "topic_already_exists" in str(exc).lower():
                    logger.debug("Kafka topic already exists: %s", topic)
                else:
                    logger.warning("Failed to create Kafka topic %s: %s", topic, exc)
    except ImportError:
        logger.warning("confluent-kafka not available — skipping topic creation")
    except Exception as exc:
        logger.error("Kafka admin error: %s", exc)


__all__ = ["TOPIC_CONFIGS", "get_producer_config", "get_consumer_config", "create_topics"]

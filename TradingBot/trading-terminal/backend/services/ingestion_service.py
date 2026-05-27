"""
Signal ingestion service.
Receives raw messages, stores them, and publishes RawMessageReceived events.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..domain.models import Signal, SignalSource, SignalStrength, OrderSide, AssetClass, now_utc
from ..domain.events import RawMessageReceived
from ..ports.outbound import ISignalRepository, IMessageBusPublisher
from ..adapters.kafka_publisher import KafkaTopics

logger = logging.getLogger(__name__)


class DuplicateSignalError(Exception):
    """Raised when a duplicate signal is detected via Redis dedup."""
    pass


class IngestionService:
    """
    Inbound port: receives raw messages from any source (Discord, webhook, news).
    Publishes RawMessageReceived to Kafka for downstream processing.
    """

    def __init__(
        self,
        signal_repo: ISignalRepository,
        publisher: IMessageBusPublisher,
        redis: Any = None,
    ) -> None:
        self._repo = signal_repo
        self._publisher = publisher
        self._redis = redis
        self._ingested_count = 0

    async def ingest_signal(
        self,
        source: str,
        raw_text: str,
        symbol: str | None = None,
        channel: str = "default",
        author: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> Signal:
        """
        Ingest a structured signal directly — saves to DB, publishes to Kafka.
        Returns the saved Signal object.
        """
        metadata = metadata or {}

        # Map source string to SignalSource enum
        source_map = {
            "discord": SignalSource.DISCORD,
            "news": SignalSource.NEWS,
            "webhook": SignalSource.WEBHOOK,
            "manual": SignalSource.MANUAL,
            "ai": SignalSource.AI,
        }
        signal_source = source_map.get(source.lower(), SignalSource.MANUAL)

        # Default direction to BUY if not derivable (parser will refine)
        direction = OrderSide.BUY
        if symbol:
            symbol = symbol.upper()

        # Dedup check via Redis
        if self._redis and symbol:
            dedup_key = f"signal:dedup:{source}:{symbol}:{direction.value}"
            try:
                existing = await self._redis.get(dedup_key)
                if existing:
                    logger.warning("Duplicate signal detected: %s", dedup_key)
                    raise DuplicateSignalError(f"Duplicate signal: {dedup_key}")
            except DuplicateSignalError:
                raise
            except Exception as e:
                logger.warning("Redis dedup check failed (non-fatal): %s", e)

        signal = Signal(
            source=signal_source,
            symbol=symbol or "UNKNOWN",
            direction=direction,
            raw_message=raw_text,
            parsed_text=raw_text[:500] if raw_text else None,
            confidence=0.5,
            strength=SignalStrength.MODERATE,
            metadata={**metadata, "channel": channel, "author": author},
        )

        # Save to DB
        try:
            await self._repo.save_signal(signal)
        except Exception as e:
            logger.error("Failed to save signal to DB: %s", e)
            raise

        # Publish to Kafka (non-fatal)
        try:
            event = RawMessageReceived(
                aggregate_id=signal.signal_id,
                source=source,
                channel_id=channel,
                author=author,
                content=raw_text,
                metadata=metadata,
            )
            await self._publisher.publish(KafkaTopics.RAW_MESSAGES, event)
        except Exception as e:
            logger.warning("Kafka publish failed (non-fatal): %s", e)

        # Set dedup key in Redis
        if self._redis and symbol:
            try:
                dedup_key = f"signal:dedup:{source}:{symbol}:{direction.value}"
                await self._redis.set(dedup_key, "1", ex=300)
            except Exception as e:
                logger.warning("Redis dedup set failed (non-fatal): %s", e)

        self._ingested_count += 1
        logger.info(
            "Signal ingested [%s]: source=%s symbol=%s",
            signal.signal_id, source, signal.symbol,
        )
        return signal

    async def ingest_raw_message(
        self,
        source: str,
        channel_id: str,
        author: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Ingest a raw message from any source.
        Returns the message_id for tracking.
        """
        message_id = f"msg-{uuid.uuid4().hex[:12]}"
        metadata = metadata or {}

        event = RawMessageReceived(
            aggregate_id=message_id,
            source=source,
            channel_id=channel_id,
            author=author,
            content=content,
            attachments=metadata.get("attachments", []),
            source_message_id=metadata.get("message_id"),
            metadata=metadata,
        )

        try:
            await self._publisher.publish(KafkaTopics.RAW_MESSAGES, event)
        except Exception as e:
            logger.warning("Kafka publish failed (non-fatal): %s", e)

        self._ingested_count += 1

        logger.info(
            "Ingested raw message [%s] from %s/#%s by %s (len=%d)",
            message_id, source, channel_id, author, len(content),
        )
        return message_id

    async def get_signal(self, signal_id: str) -> Signal | None:
        return await self._repo.get_signal(signal_id)

    async def list_signals(
        self,
        limit: int = 50,
        offset: int = 0,
        symbol: str | None = None,
    ) -> list[Signal]:
        return await self._repo.list_signals(limit=limit, offset=offset, symbol=symbol)

    @property
    def ingested_count(self) -> int:
        return self._ingested_count


__all__ = ["IngestionService", "DuplicateSignalError"]

"""
FastAPI dependency injection — provides service instances to routes.
"""
from __future__ import annotations

from typing import Annotated, AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.database import get_session
from ..infrastructure.redis_client import get_redis
from ..adapters.postgres_repositories import (
    PostgresSignalRepository,
    PostgresOrderRepository,
    PostgresPositionRepository,
    PostgresEventStore,
)
from ..adapters.kafka_publisher import KafkaPublisher
from ..adapters.paper_broker import PaperBroker
from ..adapters.market_data_yfinance import YFinanceMarketDataAdapter
from ..adapters.ai_claude import ClaudeAIAdapter
from ..services.ingestion_service import IngestionService
from ..services.parser_service import ParserService
from ..services.risk_service import RiskService, RiskPolicy
from ..services.order_gateway import OrderGatewayService
from ..services.execution_service import ExecutionService
from ..services.portfolio_service import PortfolioService
from ..services.audit_service import AuditService
from ..services.ai_recommendation_service import AIRecommendationService
from ..core.config import get_settings

settings = get_settings()

# ─── JWT Auth ───

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(token: str = Depends(_oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        username: str | None = payload.get("sub")
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


CurrentUser = Annotated[str, Depends(get_current_user)]


# ─── Singleton adapters (initialized at app startup) ───
_kafka_publisher: KafkaPublisher | None = None
_paper_broker: PaperBroker | None = None
_market_data: YFinanceMarketDataAdapter | None = None
_ai_adapter: ClaudeAIAdapter | None = None


def set_kafka_publisher(publisher: KafkaPublisher) -> None:
    global _kafka_publisher
    _kafka_publisher = publisher


def set_paper_broker(broker: PaperBroker) -> None:
    global _paper_broker
    _paper_broker = broker


def set_market_data(adapter: YFinanceMarketDataAdapter) -> None:
    global _market_data
    _market_data = adapter


def set_ai_adapter(adapter: ClaudeAIAdapter) -> None:
    global _ai_adapter
    _ai_adapter = adapter


# ─── FastAPI Dependencies ───

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_session() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_publisher() -> KafkaPublisher:
    if _kafka_publisher is None:
        # Return a no-op publisher rather than raising — non-fatal
        return KafkaPublisher(bootstrap_servers=settings.kafka_bootstrap_servers)
    return _kafka_publisher


def get_broker() -> PaperBroker:
    if _paper_broker is None:
        raise RuntimeError("Broker not initialized")
    return _paper_broker


def get_market_data_adapter() -> YFinanceMarketDataAdapter:
    if _market_data is None:
        raise RuntimeError("Market data adapter not initialized")
    return _market_data


def get_ai() -> ClaudeAIAdapter | None:
    return _ai_adapter


# ─── Service Dependencies ───

def get_ingestion_service(
    session: DbSession,
    publisher: KafkaPublisher = Depends(get_publisher),
) -> IngestionService:
    repo = PostgresSignalRepository(session)
    redis = get_redis()
    return IngestionService(repo, publisher, redis=redis)


def get_parser_service(
    session: DbSession,
    publisher: KafkaPublisher = Depends(get_publisher),
) -> ParserService:
    repo = PostgresSignalRepository(session)
    ai = _ai_adapter  # Optional — parser falls back to regex without AI
    return ParserService(repo, publisher, ai_adapter=ai)


def get_risk_service(
    session: DbSession,
    publisher: KafkaPublisher = Depends(get_publisher),
) -> RiskService:
    position_repo = PostgresPositionRepository(session)
    event_store = PostgresEventStore(session)
    policy = RiskPolicy(
        max_position_size_pct=settings.risk_max_position_size_pct,
        max_portfolio_exposure_pct=settings.risk_max_portfolio_exposure_pct,
        max_daily_loss_pct=settings.risk_max_daily_loss_pct,
        min_confidence=settings.risk_min_confidence,
        min_risk_reward=settings.risk_min_risk_reward,
        max_open_positions=settings.risk_max_open_positions,
        blacklisted_symbols=settings.blacklisted_symbols_set,
    )
    redis = get_redis()
    return RiskService(
        position_repo, event_store, publisher, policy,
        settings.paper_initial_cash,
        db_session=session,
        redis=redis,
    )


def get_order_gateway(
    session: DbSession,
    publisher: KafkaPublisher = Depends(get_publisher),
) -> OrderGatewayService:
    order_repo = PostgresOrderRepository(session)
    event_store = PostgresEventStore(session)
    return OrderGatewayService(order_repo, event_store, publisher)


def get_execution_service(
    session: DbSession,
    publisher: KafkaPublisher = Depends(get_publisher),
    broker: PaperBroker = Depends(get_broker),
) -> ExecutionService:
    order_repo = PostgresOrderRepository(session)
    event_store = PostgresEventStore(session)
    redis = get_redis()
    return ExecutionService(order_repo, broker, event_store, publisher, "paper", redis=redis)


def get_portfolio_service(
    session: DbSession,
    publisher: KafkaPublisher = Depends(get_publisher),
) -> PortfolioService:
    position_repo = PostgresPositionRepository(session)
    event_store = PostgresEventStore(session)
    # Pass the paper broker so portfolio can delegate to it
    return PortfolioService(
        position_repo, event_store, publisher,
        settings.paper_initial_cash,
        broker=_paper_broker,
    )


def get_audit_service(session: DbSession) -> AuditService:
    event_store = PostgresEventStore(session)
    return AuditService(event_store)


def get_ai_recommendation_service() -> AIRecommendationService:
    # AI and market data may be None — service handles gracefully
    return AIRecommendationService(_ai_adapter, _market_data)


__all__ = [
    "DbSession",
    "CurrentUser", "get_current_user",
    "set_kafka_publisher", "set_paper_broker", "set_market_data", "set_ai_adapter",
    "get_ingestion_service", "get_parser_service", "get_risk_service",
    "get_order_gateway", "get_execution_service", "get_portfolio_service",
    "get_audit_service", "get_ai_recommendation_service",
    "get_market_data_adapter", "get_ai",
]

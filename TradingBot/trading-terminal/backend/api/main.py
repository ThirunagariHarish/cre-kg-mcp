"""
FastAPI application factory with lifespan management.
Bloomberg-style Trading Terminal — main entry point.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routers import signals, orders, positions, risk, market_data, ai, audit
from .routers import auth as auth_router
from .routers import watchlist as watchlist_router
from .routers import alerts as alerts_router
from .routers import fleet as fleet_router
from .routers import approvals as approvals_router
from .routers import robinhood as robinhood_router
from .routers import backtest as backtest_router
from .websockets import router as ws_router, broadcast_event
from .dependencies import (
    set_kafka_publisher, set_paper_broker, set_market_data, set_ai_adapter,
    get_current_user,
)
from ..core.config import get_settings
from ..core.logging import configure_logging
from ..infrastructure.database import create_engine, create_session_factory, close_engine
from ..infrastructure.redis_client import init_redis, close_redis, get_redis
from ..infrastructure.kafka_config import create_topics
from ..adapters.kafka_publisher import KafkaPublisher
from ..adapters.paper_broker import PaperBroker
from ..adapters.market_data_yfinance import YFinanceMarketDataAdapter
from ..adapters.ai_claude import ClaudeAIAdapter
from ..services.robinhood_execution_service import RobinhoodExecutionService, set_execution_service
from ..adapters.unusual_whales_adapter import UnusualWhalesAdapter
from ..services.strategies.uw_flow_scanner import UWFlowScannerAgent
from ..services.strategies.uw_darkpool_agent import UWDarkPoolAgent
from ..services.strategies.uw_earnings_agent import UWEarningsAgent
from ..services.strategies.uw_congress_agent import UWCongressAgent
from ..services.strategies.uw_short_squeeze import UWShortSqueezeAgent

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    configure_logging(
        log_level="DEBUG" if settings.debug else "INFO",
        json_logs=settings.environment == "production",
        service_name="trading-terminal",
    )
    logger.info("Starting %s v%s [%s]", settings.app_name, settings.app_version, settings.environment)

    # ── Database ──
    try:
        engine = create_engine(
            settings.postgres_url,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
            echo=settings.postgres_echo,
        )
        create_session_factory(engine)
        logger.info("Database initialized")
    except Exception as exc:
        logger.error("Database initialization failed: %s", exc)

    # ── Redis ──
    try:
        await init_redis(settings.redis_url)
    except Exception as exc:
        logger.warning("Redis initialization failed (non-fatal): %s", exc)

    # ── Kafka ──
    kafka_publisher = KafkaPublisher(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        client_id="trading-terminal-api",
    )
    try:
        await kafka_publisher.start()
        await create_topics(settings.kafka_bootstrap_servers)
        set_kafka_publisher(kafka_publisher)
        logger.info("Kafka publisher ready")
    except Exception as exc:
        logger.warning("Kafka unavailable (non-fatal): %s", exc)

    # ── Paper Broker ──
    paper_broker = PaperBroker(
        initial_cash=settings.paper_initial_cash,
        slippage_bps=settings.paper_slippage_bps,
    )
    await paper_broker.connect()
    set_paper_broker(paper_broker)

    # ── Market Data ──
    market_data_adapter = YFinanceMarketDataAdapter()
    set_market_data(market_data_adapter)

    # ── AI ──
    if settings.anthropic_api_key:
        ai_adapter = ClaudeAIAdapter(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
        )
        set_ai_adapter(ai_adapter)
        logger.info("Claude AI adapter configured")
    else:
        logger.warning("ANTHROPIC_API_KEY not set — AI features disabled")

    # ── Robinhood Execution Agent ──
    rh_service = RobinhoodExecutionService(paper_mode=settings.robinhood_paper_mode)
    await rh_service.start()
    set_execution_service(rh_service)

    # ── Background Tasks ──
    WATCHLIST_SYMBOLS = [
        "AAPL", "NVDA", "TSLA", "MSFT", "AMD", "META", "GOOGL", "AMZN", "SPY", "QQQ"
    ]

    async def price_feed_task() -> None:
        """Update watchlist prices in Redis every 5s and broadcast via WebSocket."""
        while True:
            try:
                import yfinance as yf  # type: ignore
                tickers = yf.Tickers(" ".join(WATCHLIST_SYMBOLS))
                prices: dict[str, Any] = {}
                for sym in WATCHLIST_SYMBOLS:
                    try:
                        info = tickers.tickers[sym].fast_info
                        last = float(getattr(info, "last_price", None) or 0)
                        prev = float(getattr(info, "previous_close", None) or 0)
                        prices[sym] = {
                            "symbol": sym,
                            "last": last,
                            "previousClose": prev,
                            "change": round(last - prev, 4),
                            "changePercent": round((last - prev) / max(prev, 0.01) * 100, 2),
                            "volume": int(getattr(info, "three_month_average_volume", None) or 0),
                            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                        }
                    except Exception:
                        pass
                if prices:
                    redis = get_redis()
                    if redis:
                        try:
                            await redis.set("prices:watchlist", json.dumps(prices), ex=30)
                        except Exception as e:
                            logger.debug("Redis price cache set failed: %s", e)
                    await broadcast_event("QUOTE_UPDATE", prices)
            except Exception as e:
                logger.warning("Price feed error: %s", e)
            await asyncio.sleep(5)

    async def position_update_task() -> None:
        """Update position P&L every 5s using cached prices."""
        while True:
            try:
                redis = get_redis()
                if redis and paper_broker:
                    prices_json = await redis.get("prices:watchlist")
                    if prices_json:
                        raw_prices = json.loads(prices_json)
                        prices = {sym: float(data["last"]) for sym, data in raw_prices.items() if data.get("last")}
                        if prices:
                            filled_orders = await paper_broker.process_pending_orders(prices)
                            for order in filled_orders:
                                await broadcast_event("ORDER_UPDATE", order.model_dump())
                            positions_list = await paper_broker.get_positions()
                            await broadcast_event(
                                "POSITION_UPDATE",
                                [p.model_dump() for p in positions_list],
                            )
            except Exception as e:
                logger.warning("Position update error: %s", e)
            await asyncio.sleep(5)

    # ── UW Strategy Agents ──
    uw_adapter = UnusualWhalesAdapter(
        api_key=settings.uw_api_key,
        client_api_id=settings.uw_client_api_id,
    )
    uw_agents = [
        UWFlowScannerAgent(uw_adapter),
        UWDarkPoolAgent(uw_adapter),
        UWEarningsAgent(uw_adapter),
        UWCongressAgent(uw_adapter),
        UWShortSqueezeAgent(uw_adapter),
    ]

    tasks: list[asyncio.Task] = []
    tasks.append(asyncio.create_task(price_feed_task()))
    tasks.append(asyncio.create_task(position_update_task()))
    tasks.append(asyncio.create_task(rh_service.run_queue_loop()))
    logger.info("Robinhood execution agent started (paper=%s)", settings.robinhood_paper_mode)

    if settings.uw_api_key:
        for agent in uw_agents:
            tasks.append(asyncio.create_task(agent.run()))
        logger.info("Started %d UW strategy agents", len(uw_agents))
    else:
        logger.warning("UW_API_KEY not set — UW strategy agents disabled")

    logger.info("%s ready on %s:%d", settings.app_name, settings.host, settings.port)
    yield

    # ── Shutdown ──
    logger.info("Shutting down background tasks...")
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("Shutting down services...")
    await rh_service.stop()
    await paper_broker.disconnect()
    try:
        await kafka_publisher.stop()
    except Exception:
        pass
    await close_redis()
    await close_engine()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Bloomberg-style Trading Terminal — AI-assisted, risk-gated trading.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception Handlers ──
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception: %s %s — %s", request.method, request.url, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(exc)},
        )

    # ── Routers ──
    _auth_dep = [Depends(get_current_user)]
    app.include_router(auth_router.router)                              # public
    app.include_router(signals.router,         dependencies=_auth_dep)
    app.include_router(orders.router,          dependencies=_auth_dep)
    app.include_router(positions.router,       dependencies=_auth_dep)
    app.include_router(risk.router,            dependencies=_auth_dep)
    app.include_router(market_data.router,     dependencies=_auth_dep)
    app.include_router(ai.router,              dependencies=_auth_dep)
    app.include_router(audit.router,           dependencies=_auth_dep)
    app.include_router(watchlist_router.router, dependencies=_auth_dep)
    app.include_router(alerts_router.router,   dependencies=_auth_dep)
    app.include_router(fleet_router.router,    dependencies=_auth_dep)
    app.include_router(approvals_router.router, dependencies=_auth_dep)
    app.include_router(robinhood_router.router, dependencies=_auth_dep)
    app.include_router(backtest_router.router,  dependencies=_auth_dep)
    app.include_router(ws_router,              dependencies=_auth_dep)

    # ── Health ──
    @app.get("/health", tags=["system"])
    async def health() -> dict[str, Any]:
        return {
            "status": "healthy",
            "service": "trading-terminal",
            "version": settings.app_version,
            "environment": settings.environment,
        }

    @app.get("/", tags=["system"])
    async def root() -> dict[str, Any]:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers,
    )

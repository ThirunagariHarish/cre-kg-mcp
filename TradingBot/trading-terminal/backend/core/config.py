"""
Application configuration using Pydantic Settings.
All values can be overridden via environment variables.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── App ───
    app_name: str = "Bloomberg Trading Terminal"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = Field(default="development", pattern="^(development|staging|production)$")
    secret_key: str = "change-me-in-production-use-32-chars-min"

    # ─── Server ───
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False

    # ─── PostgreSQL ───
    postgres_url: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading_terminal"
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 20
    postgres_echo: bool = False

    # ─── Redis ───
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 10
    redis_decode_responses: bool = True

    # ─── Kafka ───
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_consumer_group: str = "trading-terminal"
    kafka_auto_offset_reset: str = "latest"
    kafka_enable_auto_commit: bool = True

    # ─── Alpaca ───
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_mode: str = Field(default="paper", pattern="^(paper|live)$")

    # ─── Discord ───
    discord_token: str = ""
    discord_monitored_channels: str = ""  # Comma-separated channel names

    # ─── Anthropic Claude ───
    anthropic_api_key: str = ""
    claude_model: str = "claude-3-5-sonnet-20241022"
    claude_max_tokens: int = 1024

    # ─── Risk Policy ───
    risk_max_position_size_pct: float = 5.0
    risk_max_portfolio_exposure_pct: float = 80.0
    risk_max_daily_loss_pct: float = 3.0
    risk_min_confidence: float = 0.4
    risk_min_risk_reward: float = 1.5
    risk_max_open_positions: int = 10
    risk_blacklisted_symbols: str = ""  # Comma-separated

    # ─── Paper Broker ───
    paper_initial_cash: float = 100_000.0
    paper_slippage_bps: float = 5.0

    # ─── Auth ───
    dashboard_username: str = "admin"
    dashboard_password_hash: str = ""  # bcrypt hash — set via Doppler DASHBOARD_PASSWORD_HASH
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours

    # ─── Robinhood ───
    robinhood_username: str = ""
    robinhood_password: str = ""
    robinhood_paper_mode: bool = True  # Always start in paper mode

    # ─── Unusual Whales ───
    uw_api_key: str = ""  # env var UW_API_KEY
    uw_client_api_id: str = "100001"

    # ─── CORS ───
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def discord_channels_list(self) -> list[str]:
        return [c.strip() for c in self.discord_monitored_channels.split(",") if c.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def blacklisted_symbols_set(self) -> set[str]:
        return {s.strip().upper() for s in self.risk_blacklisted_symbols.split(",") if s.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]

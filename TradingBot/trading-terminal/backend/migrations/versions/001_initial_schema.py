"""Initial schema — all tables for the Bloomberg Trading Terminal.

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "001"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Signals ──
    op.create_table(
        "signals",
        sa.Column("signal_id", sa.String(50), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("asset_class", sa.String(20), nullable=False, server_default="equity"),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("raw_message", sa.Text, nullable=False),
        sa.Column("parsed_text", sa.Text),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0.5"),
        sa.Column("strength", sa.String(20), nullable=False, server_default="moderate"),
        sa.Column("suggested_entry", sa.Numeric(15, 4)),
        sa.Column("suggested_stop", sa.Numeric(15, 4)),
        sa.Column("suggested_target", sa.Numeric(15, 4)),
        sa.Column("timeframe", sa.String(20)),
        sa.Column("score", sa.Numeric(5, 4)),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("idx_signals_symbol", "signals", ["symbol", "created_at"])
    op.create_index("idx_signals_source", "signals", ["source", "created_at"])
    op.create_index("idx_signals_created", "signals", ["created_at"])

    # ── Orders ──
    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(50), primary_key=True),
        sa.Column("signal_id", sa.String(50)),
        sa.Column("broker_order_id", sa.String(100)),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("limit_price", sa.Numeric(15, 4)),
        sa.Column("stop_price", sa.Numeric(15, 4)),
        sa.Column("time_in_force", sa.String(10), nullable=False, server_default="day"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("filled_quantity", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("average_fill_price", sa.Numeric(15, 4)),
        sa.Column("commission", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("asset_class", sa.String(20), nullable=False, server_default="equity"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("filled_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("idx_orders_status", "orders", ["status", "created_at"])
    op.create_index("idx_orders_symbol", "orders", ["symbol", "created_at"])
    op.create_index("idx_orders_signal_id", "orders", ["signal_id"])
    op.create_index("idx_orders_broker_id", "orders", ["broker_order_id"])

    # ── Order Events (Event Store) ──
    op.create_table(
        "order_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("aggregate_id", sa.String(50), nullable=False),
        sa.Column("aggregate_type", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("correlation_id", sa.String(36)),
    )
    op.create_index("idx_events_aggregate", "order_events", ["aggregate_id", "timestamp"])
    op.create_index("idx_events_type", "order_events", ["event_type", "timestamp"])
    op.create_index("idx_events_timestamp", "order_events", ["timestamp"])

    # ── Positions ──
    op.create_table(
        "positions",
        sa.Column("position_id", sa.String(50), primary_key=True),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("asset_class", sa.String(20), nullable=False, server_default="equity"),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("avg_entry_price", sa.Numeric(15, 4), nullable=False),
        sa.Column("current_price", sa.Numeric(15, 4)),
        sa.Column("realized_pnl", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("idx_positions_symbol_status", "positions", ["symbol", "status"])
    op.create_index("idx_positions_status", "positions", ["status", "opened_at"])

    # ── Portfolio Snapshots ──
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("cash_balance", sa.Numeric(18, 4), nullable=False),
        sa.Column("total_equity", sa.Numeric(18, 4), nullable=False),
        sa.Column("total_market_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(18, 4), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(18, 4), nullable=False),
        sa.Column("open_positions_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("snapshot_data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_portfolio_snapshots_created", "portfolio_snapshots", ["created_at"])

    # ── Risk Decisions ──
    op.create_table(
        "risk_decisions",
        sa.Column("decision_id", sa.String(50), primary_key=True),
        sa.Column("signal_id", sa.String(50), nullable=False),
        sa.Column("order_id", sa.String(50)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("checks_passed", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("checks_failed", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("position_size_recommended", sa.Numeric(18, 8)),
        sa.Column("max_loss_allowed", sa.Numeric(15, 4)),
        sa.Column("portfolio_exposure_pct", sa.Numeric(8, 4)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_risk_decisions_signal", "risk_decisions", ["signal_id"])
    op.create_index("idx_risk_decisions_status", "risk_decisions", ["status", "created_at"])

    # ── Audit Log ──
    op.create_table(
        "audit_log",
        sa.Column("entry_id", sa.String(50), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(50), nullable=False),
        sa.Column("aggregate_type", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("actor", sa.String(100), nullable=False, server_default="system"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_audit_aggregate", "audit_log", ["aggregate_id", "created_at"])
    op.create_index("idx_audit_type", "audit_log", ["event_type", "created_at"])
    op.create_index("idx_audit_created", "audit_log", ["created_at"])

    # ── Market Data OHLCV ──
    op.create_table(
        "market_data_ohlcv",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("interval", sa.String(10), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(15, 6), nullable=False),
        sa.Column("high", sa.Numeric(15, 6), nullable=False),
        sa.Column("low", sa.Numeric(15, 6), nullable=False),
        sa.Column("close", sa.Numeric(15, 6), nullable=False),
        sa.Column("volume", sa.Numeric(20, 2), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "interval", "timestamp", name="uq_ohlcv_symbol_interval_ts"),
    )
    op.create_index("idx_ohlcv_symbol_ts", "market_data_ohlcv", ["symbol", "interval", "timestamp"])


def downgrade() -> None:
    op.drop_table("market_data_ohlcv")
    op.drop_table("audit_log")
    op.drop_table("risk_decisions")
    op.drop_table("portfolio_snapshots")
    op.drop_table("positions")
    op.drop_table("order_events")
    op.drop_table("orders")
    op.drop_table("signals")

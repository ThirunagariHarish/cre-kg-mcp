# Backtesting Engine -- Data Model

---

## 1. PostgreSQL DDL

```sql
-- ============================================================
-- Backtest Engine Schema
-- Run with: psql $POSTGRES_URL -f backtest_schema.sql
-- Rollback: DROP TABLE backtest_trades, backtest_metrics, backtest_runs CASCADE;
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS backtest_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      VARCHAR(64)  NOT NULL,
    symbols         TEXT         NOT NULL,       -- comma-separated: "AAPL,NVDA,TSLA"
    start_date      DATE         NOT NULL,
    end_date        DATE         NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
                    -- PENDING | RUNNING | COMPLETED | FAILED | PARTIAL
    initial_capital FLOAT        NOT NULL DEFAULT 100000.0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,

    CONSTRAINT chk_run_status CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'PARTIAL')
    ),
    CONSTRAINT chk_date_range CHECK (start_date < end_date)
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_agent ON backtest_runs (agent_name);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_status ON backtest_runs (status);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created ON backtest_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID         NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    symbol          VARCHAR(20)  NOT NULL,
    direction       VARCHAR(10)  NOT NULL,       -- 'LONG' | 'SHORT'
    entry_date      DATE         NOT NULL,
    exit_date       DATE,
    entry_price     FLOAT        NOT NULL,
    exit_price      FLOAT,
    quantity         FLOAT        NOT NULL,
    pnl             FLOAT,
    pnl_pct         FLOAT,
    commission      FLOAT        NOT NULL DEFAULT 0.0,
    exit_reason     VARCHAR(30),                 -- 'STOP_LOSS' | 'PROFIT_TARGET' | 'SIGNAL_EXIT' | 'TIME_EXIT' | 'EOD'
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_direction CHECK (direction IN ('LONG', 'SHORT'))
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades (run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_symbol ON backtest_trades (symbol);

CREATE TABLE IF NOT EXISTS backtest_metrics (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id            UUID         NOT NULL UNIQUE REFERENCES backtest_runs(id) ON DELETE CASCADE,
    agent_name        VARCHAR(64)  NOT NULL,

    -- Performance metrics
    total_return_pct  FLOAT        NOT NULL DEFAULT 0.0,
    annualized_return FLOAT        NOT NULL DEFAULT 0.0,
    sharpe_ratio      FLOAT        NOT NULL DEFAULT 0.0,
    sortino_ratio     FLOAT        NOT NULL DEFAULT 0.0,
    max_drawdown_pct  FLOAT        NOT NULL DEFAULT 0.0,
    win_rate          FLOAT        NOT NULL DEFAULT 0.0,
    profit_factor     FLOAT        NOT NULL DEFAULT 0.0,
    calmar_ratio      FLOAT        NOT NULL DEFAULT 0.0,

    -- Trade statistics
    total_trades      INT          NOT NULL DEFAULT 0,
    winning_trades    INT          NOT NULL DEFAULT 0,
    losing_trades     INT          NOT NULL DEFAULT 0,
    avg_trade_pnl     FLOAT        NOT NULL DEFAULT 0.0,
    avg_win           FLOAT        NOT NULL DEFAULT 0.0,
    avg_loss          FLOAT        NOT NULL DEFAULT 0.0,
    largest_win       FLOAT        NOT NULL DEFAULT 0.0,
    largest_loss      FLOAT        NOT NULL DEFAULT 0.0,
    avg_hold_days     FLOAT        NOT NULL DEFAULT 0.0,

    -- Composite ranking
    ranking_score     FLOAT        NOT NULL DEFAULT 0.0,

    -- Equity curve (stored as JSON array of {date, nav} objects)
    equity_curve_json TEXT,

    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_win_rate CHECK (win_rate >= 0.0 AND win_rate <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_backtest_metrics_agent ON backtest_metrics (agent_name);
CREATE INDEX IF NOT EXISTS idx_backtest_metrics_ranking ON backtest_metrics (ranking_score DESC);
```

---

## 2. Pydantic Domain Models (Python)

These live in `backend/services/backtest/models.py`. They are NOT SQLAlchemy ORM models -- consistent with the existing codebase pattern of raw SQL + Pydantic domain models.

```python
"""
Backtest domain models -- pure Pydantic, no infrastructure imports.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class BacktestStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    PROFIT_TARGET = "PROFIT_TARGET"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    TIME_EXIT = "TIME_EXIT"
    EOD = "EOD"


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class BacktestRun(BaseModel):
    model_config = ConfigDict(frozen=False)

    id: str = Field(default_factory=_new_id)
    agent_name: str
    symbols: str                            # comma-separated
    start_date: date
    end_date: date
    status: BacktestStatus = BacktestStatus.PENDING
    initial_capital: float = 100_000.0
    error_message: str | None = None
    created_at: datetime = Field(default_factory=_now_utc)
    completed_at: datetime | None = None

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.symbols.split(",") if s.strip()]


class BacktestTrade(BaseModel):
    model_config = ConfigDict(frozen=False)

    id: str = Field(default_factory=_new_id)
    run_id: str
    symbol: str
    direction: TradeDirection
    entry_date: date
    exit_date: date | None = None
    entry_price: float
    exit_price: float | None = None
    quantity: float
    pnl: float | None = None
    pnl_pct: float | None = None
    commission: float = 0.0
    exit_reason: ExitReason | None = None
    created_at: datetime = Field(default_factory=_now_utc)


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(frozen=False)

    id: str = Field(default_factory=_new_id)
    run_id: str
    agent_name: str

    # Performance
    total_return_pct: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    calmar_ratio: float = 0.0

    # Trade stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_trade_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_hold_days: float = 0.0

    # Ranking
    ranking_score: float = 0.0

    # Equity curve (serialized)
    equity_curve_json: str | None = None

    created_at: datetime = Field(default_factory=_now_utc)


class BacktestRunRequest(BaseModel):
    """API request body for POST /api/backtest/run"""
    agent_name: str
    symbols: list[str]
    start_date: date
    end_date: date
    initial_capital: float = 100_000.0


class BacktestRankingRow(BaseModel):
    """Single row returned by GET /api/backtest/rankings"""
    rank: int
    agent_name: str
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    calmar_ratio: float
    total_trades: int
    ranking_score: float
    last_run_at: datetime | None = None
```

---

## 3. TypeScript Types (Frontend)

These live in `frontend/src/types/backtest.ts`.

```typescript
// ============================================================
// Backtest Types
// ============================================================

export interface BacktestRunRequest {
  agent_name: string
  symbols: string[]
  start_date: string   // YYYY-MM-DD
  end_date: string     // YYYY-MM-DD
  initial_capital?: number
}

export interface BacktestRunResponse {
  run_id: string
  agent_name: string
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'PARTIAL'
  created_at: string
}

export interface BacktestRankingRow {
  rank: number
  agent_name: string
  total_return_pct: number
  sharpe_ratio: number
  sortino_ratio: number
  max_drawdown_pct: number
  win_rate: number
  profit_factor: number
  calmar_ratio: number
  total_trades: number
  ranking_score: number
  last_run_at: string | null
}

export interface BacktestTradeRow {
  id: string
  run_id: string
  symbol: string
  direction: 'LONG' | 'SHORT'
  entry_date: string
  exit_date: string | null
  entry_price: number
  exit_price: number | null
  quantity: number
  pnl: number | null
  pnl_pct: number | null
  exit_reason: string | null
}

export interface BacktestAgentDetail {
  agent_name: string
  run_id: string
  status: string
  metrics: {
    total_return_pct: number
    annualized_return: number
    sharpe_ratio: number
    sortino_ratio: number
    max_drawdown_pct: number
    win_rate: number
    profit_factor: number
    calmar_ratio: number
    total_trades: number
    winning_trades: number
    losing_trades: number
    avg_trade_pnl: number
    avg_win: number
    avg_loss: number
    largest_win: number
    largest_loss: number
    avg_hold_days: number
    ranking_score: number
  }
  equity_curve: Array<{ date: string; nav: number }>
  start_date: string
  end_date: string
  symbols: string[]
}

export type BacktestSortKey =
  | 'ranking_score'
  | 'sharpe_ratio'
  | 'total_return_pct'
  | 'win_rate'
  | 'max_drawdown_pct'
  | 'profit_factor'
```

---

## 4. Field-Level Security Notes

All backtest tables contain no PII -- they store only agent performance data against public market tickers. No field-level security restrictions are required beyond the existing JWT-gated API authentication. The `CurrentUser` dependency already gates all API endpoints.

# Backtesting Engine + Agent Ranking Architecture

> **Version**: 1.0.0
> **Author**: Atlas (Staff Architect)
> **Date**: 2026-05-27
> **Status**: PROPOSED

---

## 1. Context

The trading terminal runs 9 agents (7 with quantifiable trading strategies, 2 infrastructure-only: `discord_ingestor`, `ai_analyzer`). Today the `AgentAttributionPanel` derives ranking from live fleet metrics that are seeded with zeros. There is a stub `BacktestPanel` with no engine behind it.

This design adds:

1. A vectorized, pandas-based backtest engine that replays OHLCV data through each agent's signal logic.
2. A composite ranking score that normalizes 7 performance metrics across agents.
3. Persistent storage of backtest runs, trades, and metrics in PostgreSQL (reusing the existing async SQLAlchemy infrastructure).
4. REST API endpoints for triggering runs and querying results.
5. Frontend wiring so `AgentAttributionPanel` renders backtest-derived rankings.

### Agents in scope for backtesting (7 of 9)

| Agent Name | Strategy Type |
|---|---|
| `breakout_trader` | Price breaks 20-day high + volume confirmation |
| `albert_pro_trader` | RSI(14) < 30 mean reversion on SPY |
| `vcp_setups_trader` | Volatility Contraction Pattern breakout |
| `dark_pool_followthrough` | Enter day+1 after 3+ dark pool prints; 5-day hold |
| `earnings_momentum` | Gap-and-go after earnings gap > 3% |
| `iron_condor` | Sell 20-delta strangle on high-IV stocks; premium capture |
| `gap_executor` | Pre-market gap > 2%; enter open, exit 10am or first profitable close |

`discord_ingestor` and `ai_analyzer` are data/AI infrastructure agents with no backtestable signal logic. They are excluded.

---

## 2. Architectural Decisions

### ADR-1: Synchronous pandas engine, async API wrapper

**Decision**: The backtest engine itself is synchronous pandas code. The `BacktestService` wraps it in `asyncio.to_thread()` for non-blocking execution within FastAPI.

**Rationale**: Vectorized pandas operations are CPU-bound and single-threaded. Running them in a thread executor avoids blocking the event loop without the complexity of multiprocessing. For a single-user terminal this is sufficient.

**Tradeoff**: Cannot run many parallel backtests. Acceptable because this is a personal terminal, not a multi-tenant SaaS.

### ADR-2: PostgreSQL for persistence, not in-memory

**Decision**: Store `backtest_runs`, `backtest_trades`, and `backtest_metrics` in PostgreSQL using the existing `get_session()` infrastructure.

**Rationale**: The codebase already has `PostgresSignalRepository`, `PostgresOrderRepository`, etc. using raw SQL via `sqlalchemy.text()`. Adding three more tables is low friction and gives persistence across restarts. The existing `backend/infrastructure/database.py` provides the async engine and session factory.

**Tradeoff**: Requires a DB migration. Mitigated by providing the DDL as a standalone SQL file that can be run via `psql` or embedded in an Alembic migration.

### ADR-3: Strategy classes live in `backend/services/backtest/strategies/`

**Decision**: One Python file per strategy, all inheriting from `AgentStrategyBase`. The strategies directory is a flat module, not a plugin system.

**Rationale**: With only 7 strategies, a plugin/registry pattern is over-engineering. Import them explicitly in a `STRATEGY_REGISTRY` dict.

### ADR-4: yfinance for historical data, same adapter

**Decision**: Reuse `YFinanceMarketDataAdapter.get_ohlcv()` but call `yfinance.download()` directly in the backtest engine for bulk historical data (1-2 years). The adapter's existing method uses `ticker.history()` which works for longer periods.

**Rationale**: No new data dependency. yfinance provides adjusted OHLCV for free. For backtesting we call it synchronously within the thread executor.

**Risk**: yfinance rate limits. Mitigated by caching downloaded data in a local parquet file per symbol per date range.

### ADR-5: Composite ranking score uses min-max normalization

**Decision**: Each metric is normalized to [0, 1] across all agents using `(value - min) / (max - min)`. The composite score is a weighted sum.

**Rationale**: Simple, interpretable, and does not require distributional assumptions. With only 7 agents, more sophisticated methods (z-score, percentile) offer no advantage.

### ADR-6: Frontend reads from `/api/backtest/rankings`, not fleet metrics

**Decision**: The `AgentAttributionPanel` will add a toggle: "Live Metrics" vs "Backtest Rankings". When in backtest mode, it fetches from the new endpoint.

**Rationale**: Preserves the existing live P&L attribution view while adding the new backtest-driven ranking. Users can compare live performance against historical backtest performance.

---

## 3. Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| yfinance data gaps (missing bars, adjusted close changes) | Medium | Validate DataFrame shape before processing; skip agents with insufficient data and mark run as `PARTIAL` |
| `iron_condor` strategy requires options data not available in yfinance OHLCV | High | Simulate with a simplified model: use VIX as IV proxy, compute theoretical premium from Black-Scholes approximation on the underlying. Document this as a known limitation. |
| Long-running backtests block the API thread | Medium | `asyncio.to_thread()` prevents event loop blocking. Add a 120-second timeout. |
| Database migration breaks existing schema | Low | DDL uses `CREATE TABLE IF NOT EXISTS`. No changes to existing tables. Rollback is `DROP TABLE backtest_runs, backtest_trades, backtest_metrics CASCADE;` |
| Survivorship bias in symbol selection | Medium | Document that backtests use current ticker lists, not delisted stocks. This is a known limitation of retail-grade backtesting. |

---

## 4. Rollback Strategy

### Database

```sql
-- Rollback: remove all backtest tables
DROP TABLE IF EXISTS backtest_trades CASCADE;
DROP TABLE IF EXISTS backtest_metrics CASCADE;
DROP TABLE IF EXISTS backtest_runs CASCADE;
```

### Backend

All new code lives in:
- `backend/services/backtest/` (new directory)
- `backend/api/routers/backtest.py` (new file)
- `backend/adapters/backtest_repository.py` (new file)

Removing these files and the router registration in `main.py` fully reverts the feature. No existing files are modified except:
- `backend/api/dependencies.py` (add backtest service dependency)
- The main FastAPI app file (register the router)

### Frontend

New files only:
- `frontend/src/hooks/useBacktestRankings.ts`
- `frontend/src/types/backtest.ts`

Modified files:
- `frontend/src/components/analytics/AgentAttributionPanel.tsx` (add toggle)
- `frontend/src/lib/queryKeys.ts` (add keys)

Revert by removing the new files and undoing the two modifications.

# Backtesting Engine -- API Contracts

---

## 1. Backend Endpoints (FastAPI)

All endpoints require `Authorization: Bearer <JWT>` header. All responses are JSON.

---

### 1.1 POST /api/backtest/run

Trigger a backtest run for a single agent across one or more symbols.

**Request Body**

```json
{
  "agent_name": "breakout_trader",
  "symbols": ["AAPL", "NVDA", "TSLA", "MSFT", "AMD"],
  "start_date": "2024-06-01",
  "end_date": "2026-05-27",
  "initial_capital": 100000
}
```

**Validation Rules**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `agent_name` | string | yes | Must be one of the 7 backtestable agents |
| `symbols` | string[] | yes | 1-20 symbols, each 1-10 uppercase letters |
| `start_date` | date (YYYY-MM-DD) | yes | Must be in the past |
| `end_date` | date (YYYY-MM-DD) | yes | Must be after start_date, at most today |
| `initial_capital` | float | no | Default 100000. Min 1000, max 10000000 |

**Success Response: 202 Accepted**

```json
{
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "agent_name": "breakout_trader",
  "status": "RUNNING",
  "symbols": ["AAPL", "NVDA", "TSLA", "MSFT", "AMD"],
  "created_at": "2026-05-27T14:30:00Z"
}
```

Note: The backtest executes synchronously within `asyncio.to_thread()`. Despite the 202 status code, the response is returned only after completion. For runs expected to take longer than 30 seconds, consider the polling pattern via `GET /api/backtest/{agent}/results`.

**Error Responses**

| Status | Condition | Body |
|---|---|---|
| 400 | Invalid agent_name | `{"detail": "Unknown agent: foo. Valid agents: breakout_trader, ..."}` |
| 400 | Invalid date range | `{"detail": "start_date must be before end_date"}` |
| 400 | Too many symbols | `{"detail": "Maximum 20 symbols per backtest run"}` |
| 422 | Validation error | Standard FastAPI validation error |
| 500 | Engine failure | `{"detail": "Backtest failed: <error message>"}` |

---

### 1.2 GET /api/backtest/rankings

Return all agents ranked by composite score, using the most recent completed backtest run for each agent.

**Query Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `sort_by` | string | `ranking_score` | One of: `ranking_score`, `sharpe_ratio`, `total_return_pct`, `win_rate`, `max_drawdown_pct`, `profit_factor` |
| `order` | string | `desc` | `asc` or `desc` |

**Success Response: 200 OK**

```json
{
  "rankings": [
    {
      "rank": 1,
      "agent_name": "vcp_setups_trader",
      "total_return_pct": 47.3,
      "sharpe_ratio": 2.14,
      "sortino_ratio": 3.01,
      "max_drawdown_pct": -8.7,
      "win_rate": 0.68,
      "profit_factor": 2.45,
      "calmar_ratio": 5.43,
      "total_trades": 42,
      "ranking_score": 0.87,
      "last_run_at": "2026-05-27T14:35:00Z"
    },
    {
      "rank": 2,
      "agent_name": "breakout_trader",
      "total_return_pct": 31.2,
      "sharpe_ratio": 1.67,
      "sortino_ratio": 2.10,
      "max_drawdown_pct": -12.4,
      "win_rate": 0.55,
      "profit_factor": 1.89,
      "calmar_ratio": 2.52,
      "total_trades": 87,
      "ranking_score": 0.72,
      "last_run_at": "2026-05-27T14:32:00Z"
    }
  ],
  "last_updated": "2026-05-27T14:35:00Z",
  "agent_count": 7
}
```

**Error Responses**

| Status | Condition | Body |
|---|---|---|
| 200 | No backtest data yet | `{"rankings": [], "last_updated": null, "agent_count": 0}` |

---

### 1.3 GET /api/backtest/{agent_name}/results

Return the most recent backtest metrics and equity curve for a specific agent.

**Path Parameters**

| Param | Type | Description |
|---|---|---|
| `agent_name` | string | One of the 7 backtestable agent names |

**Success Response: 200 OK**

```json
{
  "agent_name": "breakout_trader",
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "COMPLETED",
  "metrics": {
    "total_return_pct": 31.2,
    "annualized_return": 18.4,
    "sharpe_ratio": 1.67,
    "sortino_ratio": 2.10,
    "max_drawdown_pct": -12.4,
    "win_rate": 0.55,
    "profit_factor": 1.89,
    "calmar_ratio": 2.52,
    "total_trades": 87,
    "winning_trades": 48,
    "losing_trades": 39,
    "avg_trade_pnl": 358.62,
    "avg_win": 892.14,
    "avg_loss": -298.21,
    "largest_win": 4521.00,
    "largest_loss": -1876.50,
    "avg_hold_days": 4.2,
    "ranking_score": 0.72
  },
  "equity_curve": [
    {"date": "2024-06-03", "nav": 100000.00},
    {"date": "2024-06-04", "nav": 100245.50},
    {"date": "2024-06-05", "nav": 99812.30}
  ],
  "start_date": "2024-06-01",
  "end_date": "2026-05-27",
  "symbols": ["AAPL", "NVDA", "TSLA", "MSFT", "AMD"]
}
```

**Error Responses**

| Status | Condition | Body |
|---|---|---|
| 404 | No completed run for agent | `{"detail": "No backtest results found for agent: breakout_trader"}` |
| 400 | Invalid agent name | `{"detail": "Unknown agent: foo"}` |

---

### 1.4 GET /api/backtest/{agent_name}/trades

Return the individual trades from the most recent backtest run for an agent.

**Path Parameters**

| Param | Type | Description |
|---|---|---|
| `agent_name` | string | One of the 7 backtestable agent names |

**Query Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 100 | Max trades to return (1-500) |
| `offset` | int | 0 | Pagination offset |
| `symbol` | string | null | Filter trades by symbol |

**Success Response: 200 OK**

```json
{
  "agent_name": "breakout_trader",
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "trades": [
    {
      "id": "t-001",
      "symbol": "NVDA",
      "direction": "LONG",
      "entry_date": "2024-07-15",
      "exit_date": "2024-07-19",
      "entry_price": 127.50,
      "exit_price": 135.20,
      "quantity": 100,
      "pnl": 770.00,
      "pnl_pct": 6.04,
      "exit_reason": "PROFIT_TARGET"
    }
  ],
  "total": 87,
  "limit": 100,
  "offset": 0
}
```

**Error Responses**

| Status | Condition | Body |
|---|---|---|
| 404 | No completed run | `{"detail": "No backtest results found for agent: breakout_trader"}` |

---

## 2. Frontend API Client Signatures

These functions live in the existing `frontend/src/lib/api/client.ts` pattern, called from React Query hooks.

```typescript
// frontend/src/hooks/useBacktestRankings.ts

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/lib/api/client'
import { QK } from '@/lib/queryKeys'
import type {
  BacktestRunRequest,
  BacktestRunResponse,
  BacktestRankingRow,
  BacktestAgentDetail,
  BacktestTradeRow,
  BacktestSortKey,
} from '@/types/backtest'

// ---- Rankings ----

interface RankingsResponse {
  rankings: BacktestRankingRow[]
  last_updated: string | null
  agent_count: number
}

export function useBacktestRankings(sortBy: BacktestSortKey = 'ranking_score') {
  return useQuery({
    queryKey: [...QK.backtestRankings, sortBy],
    queryFn: ({ signal }) =>
      apiGet<RankingsResponse>(
        '/api/backtest/rankings',
        { sort_by: sortBy, order: 'desc' },
        signal,
      ),
    staleTime: 2 * 60 * 1000,    // 2 minutes
    refetchInterval: 5 * 60 * 1000,  // 5 minutes
  })
}

// ---- Agent Detail ----

export function useBacktestAgentResults(agentName: string | null) {
  return useQuery({
    queryKey: QK.backtestAgent(agentName ?? ''),
    queryFn: ({ signal }) =>
      apiGet<BacktestAgentDetail>(
        `/api/backtest/${agentName}/results`,
        undefined,
        signal,
      ),
    enabled: !!agentName,
    staleTime: 2 * 60 * 1000,
  })
}

// ---- Agent Trades ----

interface TradesResponse {
  agent_name: string
  run_id: string
  trades: BacktestTradeRow[]
  total: number
  limit: number
  offset: number
}

export function useBacktestAgentTrades(
  agentName: string | null,
  opts?: { limit?: number; offset?: number; symbol?: string },
) {
  return useQuery({
    queryKey: [...QK.backtestAgent(agentName ?? ''), 'trades', opts],
    queryFn: ({ signal }) =>
      apiGet<TradesResponse>(
        `/api/backtest/${agentName}/trades`,
        {
          limit: opts?.limit ?? 100,
          offset: opts?.offset ?? 0,
          ...(opts?.symbol ? { symbol: opts.symbol } : {}),
        },
        signal,
      ),
    enabled: !!agentName,
    staleTime: 2 * 60 * 1000,
  })
}

// ---- Run Backtest Mutation ----

export function useRunBacktest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: BacktestRunRequest) =>
      apiPost<BacktestRunResponse>('/api/backtest/run', req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.backtestRankings })
    },
  })
}
```

### Query Key Additions to `QK`

```typescript
// Add to frontend/src/lib/queryKeys.ts
export const QK = {
  // ... existing keys ...
  backtestRankings: ['backtest', 'rankings'] as const,
  backtestAgent: (name: string) => ['backtest', 'agent', name] as const,
} as const
```

# Backtesting Engine -- Technical Plan

---

## File Structure Overview

All new files (no existing files are overwritten; 3 existing files receive additive edits).

```
backend/
  services/
    backtest/
      __init__.py                         # [NEW] Package init
      models.py                           # [NEW] Pydantic domain models
      engine.py                           # [NEW] BacktestEngine (vectorized simulator)
      service.py                          # [NEW] BacktestService (orchestrator)
      ranking.py                          # [NEW] RankingService (composite score)
      strategies/
        __init__.py                       # [NEW] STRATEGY_REGISTRY dict
        base.py                           # [NEW] AgentStrategyBase ABC
        breakout_strategy.py              # [NEW] BreakoutTrader signal logic
        albert_pro_strategy.py            # [NEW] AlbertPro RSI mean-reversion
        vcp_strategy.py                   # [NEW] VCP breakout
        dark_pool_strategy.py             # [NEW] Dark pool follow-through
        earnings_momentum_strategy.py     # [NEW] Gap-and-go after earnings
        iron_condor_strategy.py           # [NEW] Iron condor premium sim
        gap_executor_strategy.py          # [NEW] Gap executor

  adapters/
    backtest_repository.py                # [NEW] PostgreSQL repository for backtest tables

  api/
    routers/
      backtest.py                         # [NEW] FastAPI router (4 endpoints)

  # MODIFIED (additive only):
  api/dependencies.py                     # Add get_backtest_service dependency
  # The main app file that registers routers (add backtest router)

frontend/
  src/
    types/
      backtest.ts                         # [NEW] TypeScript interfaces
    hooks/
      useBacktestRankings.ts              # [NEW] React Query hooks
    lib/
      queryKeys.ts                        # MODIFIED: add backtest keys

    components/
      analytics/
        AgentAttributionPanel.tsx          # MODIFIED: add backtest ranking toggle

data/
  cache/
    ohlcv/                                # [NEW] Directory for parquet cache (gitignored)

sql/
  backtest_schema.sql                     # [NEW] DDL for the 3 tables
```

---

## Phase 1: Core Engine + Strategy Base (Backend Only)

**Scope**: Build the backtest engine, strategy base class, and 3 strategies (breakout, albert_pro, gap_executor). No API layer yet -- testable via pytest.

**Duration**: 1 focused session

### Files to Create (10)

| # | File | Purpose |
|---|---|---|
| 1 | `backend/services/backtest/__init__.py` | Package init, export service |
| 2 | `backend/services/backtest/models.py` | All Pydantic models from data-model.md |
| 3 | `backend/services/backtest/strategies/__init__.py` | `STRATEGY_REGISTRY` dict mapping agent_name -> class |
| 4 | `backend/services/backtest/strategies/base.py` | `AgentStrategyBase` ABC |
| 5 | `backend/services/backtest/strategies/breakout_strategy.py` | Breakout trader signal logic |
| 6 | `backend/services/backtest/strategies/albert_pro_strategy.py` | RSI(14) mean reversion |
| 7 | `backend/services/backtest/strategies/gap_executor_strategy.py` | Gap executor |
| 8 | `backend/services/backtest/engine.py` | `BacktestEngine` class |
| 9 | `backend/services/backtest/ranking.py` | `RankingService` composite score |
| 10 | `backend/services/backtest/service.py` | `BacktestService` orchestrator |

### Detailed Implementation Specifications

#### File 4: `strategies/base.py` -- AgentStrategyBase

```python
"""Abstract base class for all backtestable agent strategies."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import pandas as pd


@dataclass(frozen=True)
class StrategyConfig:
    """Per-strategy configuration for the backtest engine."""
    name: str
    direction: Literal["long_only", "short_only", "both"] = "long_only"
    max_positions: int = 1                    # concurrent positions per symbol
    commission_per_trade: float = 1.0         # dollars
    slippage_bps: float = 5.0                 # basis points
    default_position_size_pct: float = 10.0   # percent of capital per trade


class AgentStrategyBase(ABC):
    """
    Each agent implements this class.

    Contract:
      - generate_signals() receives a cleaned OHLCV DataFrame with columns:
        ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        indexed by integer (0..N-1), Date is a column not the index.
      - Returns a pd.Series of the same length with values:
        1  = enter long (or add)
        -1 = exit long (or enter short, depending on config)
        0  = no action
      - The strategy MUST be vectorized. No row-by-row loops.
      - Stop loss and profit targets are declared via get_config().
        The engine applies them; the strategy does not need to emit exit
        signals for stops/targets.
    """

    @abstractmethod
    def get_config(self) -> StrategyConfig:
        """Return strategy-level configuration."""
        ...

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Generate buy/sell signals from OHLCV data.

        Args:
            df: DataFrame with columns [Date, Open, High, Low, Close, Volume].
                Sorted by Date ascending. At least 60 rows guaranteed.

        Returns:
            pd.Series of int: 1 (buy), -1 (sell), 0 (hold).
            Must have same index as df.
        """
        ...

    def get_stop_loss(self, df: pd.DataFrame, entry_idx: int) -> float | None:
        """
        Optional: dynamic stop loss price for the entry at df.iloc[entry_idx].
        Default: None (engine uses a 2x ATR stop).
        """
        return None

    def get_profit_target(self, df: pd.DataFrame, entry_idx: int) -> float | None:
        """
        Optional: dynamic profit target price for the entry at df.iloc[entry_idx].
        Default: None (engine uses 2R target).
        """
        return None

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Optional hook: add indicator columns to df before generate_signals.
        The engine calls this before generate_signals() as a convenience.
        The base implementation is a no-op.
        """
        return df
```

#### File 5: `strategies/breakout_strategy.py`

```python
"""Breakout Trader: enter when price breaks above 20-day high with volume > 2x avg."""
from __future__ import annotations

import pandas as pd

from .base import AgentStrategyBase, StrategyConfig


class BreakoutStrategy(AgentStrategyBase):

    def get_config(self) -> StrategyConfig:
        return StrategyConfig(
            name="breakout_trader",
            direction="long_only",
            max_positions=1,
            default_position_size_pct=10.0,
        )

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["high_20"] = df["High"].rolling(20).max().shift(1)
        df["vol_avg_20"] = df["Volume"].rolling(20).mean()
        df["atr_14"] = _atr(df, 14)
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index)

        # Entry: close breaks above prior 20-day high AND volume > 2x average
        entry_cond = (
            (df["Close"] > df["high_20"]) &
            (df["Volume"] > 2 * df["vol_avg_20"]) &
            df["high_20"].notna()
        )
        signals[entry_cond] = 1
        return signals

    def get_stop_loss(self, df: pd.DataFrame, entry_idx: int) -> float | None:
        entry_price = df.iloc[entry_idx]["Close"]
        atr = df.iloc[entry_idx].get("atr_14")
        if atr and atr > 0:
            return entry_price - 1.5 * atr
        return entry_price * 0.97  # fallback 3% stop

    def get_profit_target(self, df: pd.DataFrame, entry_idx: int) -> float | None:
        entry_price = df.iloc[entry_idx]["Close"]
        stop = self.get_stop_loss(df, entry_idx)
        if stop:
            risk = entry_price - stop
            return entry_price + 2.0 * risk  # 2R target
        return entry_price * 1.06


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()
```

#### File 6: `strategies/albert_pro_strategy.py`

```python
"""Albert Pro Trader: RSI(14) < 30 mean reversion entries on SPY."""
from __future__ import annotations

import pandas as pd

from .base import AgentStrategyBase, StrategyConfig


class AlbertProStrategy(AgentStrategyBase):

    def get_config(self) -> StrategyConfig:
        return StrategyConfig(
            name="albert_pro_trader",
            direction="long_only",
            max_positions=1,
            default_position_size_pct=15.0,  # higher conviction on mean reversion
        )

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi_14"] = _rsi(df["Close"], 14)
        df["sma_200"] = df["Close"].rolling(200).mean()
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index)

        # Entry: RSI(14) drops below 30 AND price is above SMA(200) (uptrend filter)
        entry_cond = (
            (df["rsi_14"] < 30) &
            (df["Close"] > df["sma_200"]) &
            df["rsi_14"].notna() &
            df["sma_200"].notna()
        )
        signals[entry_cond] = 1

        # Exit: RSI(14) crosses back above 50
        exit_cond = (
            (df["rsi_14"] > 50) &
            (df["rsi_14"].shift(1) <= 50) &
            df["rsi_14"].notna()
        )
        signals[exit_cond] = -1
        return signals

    def get_stop_loss(self, df: pd.DataFrame, entry_idx: int) -> float | None:
        # 2% stop for mean reversion
        return df.iloc[entry_idx]["Close"] * 0.98

    def get_profit_target(self, df: pd.DataFrame, entry_idx: int) -> float | None:
        # Exit at RSI > 50 (signal-driven), but cap at 5% profit
        return df.iloc[entry_idx]["Close"] * 1.05


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))
```

#### File 7: `strategies/gap_executor_strategy.py`

```python
"""Gap Executor: pre-market gap > 2%; enter at open, exit at first profitable close or EOD."""
from __future__ import annotations

import pandas as pd

from .base import AgentStrategyBase, StrategyConfig


class GapExecutorStrategy(AgentStrategyBase):

    def get_config(self) -> StrategyConfig:
        return StrategyConfig(
            name="gap_executor",
            direction="long_only",
            max_positions=1,
            default_position_size_pct=8.0,
        )

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["prev_close"] = df["Close"].shift(1)
        df["gap_pct"] = (df["Open"] - df["prev_close"]) / df["prev_close"] * 100
        df["vol_avg_20"] = df["Volume"].rolling(20).mean()
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index)

        # Entry: gap up > 2% on above-average volume
        entry_cond = (
            (df["gap_pct"] > 2.0) &
            (df["Volume"] > df["vol_avg_20"]) &
            df["gap_pct"].notna()
        )
        signals[entry_cond] = 1

        # Exit same-day: if close > open (profitable day) -> exit signal
        # The engine handles EOD exit as a time-based exit
        exit_cond = (
            (df["Close"] > df["Open"]) &
            (df["gap_pct"] > 2.0) &
            df["gap_pct"].notna()
        )
        signals[exit_cond] = -1
        return signals

    def get_stop_loss(self, df: pd.DataFrame, entry_idx: int) -> float | None:
        # Stop at previous close (gap fill)
        prev_close = df.iloc[entry_idx].get("prev_close")
        if prev_close and prev_close > 0:
            return prev_close
        return df.iloc[entry_idx]["Open"] * 0.98

    def get_profit_target(self, df: pd.DataFrame, entry_idx: int) -> float | None:
        # 3% above open
        return df.iloc[entry_idx]["Open"] * 1.03
```

#### File 8: `engine.py` -- BacktestEngine

Core implementation plan. The engine receives a strategy and a DataFrame, then:

1. Calls `strategy.compute_indicators(df)` to enrich the DataFrame.
2. Calls `strategy.generate_signals(df)` to get the signal series.
3. Walks forward through the DataFrame day by day (vectorized where possible, with a single pass loop for position tracking):
   - On signal=1 and no position: open position at Close price (+ slippage).
   - On signal=-1 and has position: close position at Close price (- slippage).
   - On each bar while in position: check stop loss against Low, profit target against High.
   - Track equity curve as daily NAV.
4. At end of data: force-close any open position.
5. Compute all metrics from the trade list and equity curve.

Key metrics computation:
- **Sharpe ratio**: `mean(daily_returns) / std(daily_returns) * sqrt(252)`
- **Sortino ratio**: `mean(daily_returns) / downside_std(daily_returns) * sqrt(252)` where downside_std only considers negative returns
- **Max drawdown**: `max(peak - trough) / peak` over the equity curve
- **Win rate**: `winning_trades / total_trades`
- **Profit factor**: `sum(winning_pnl) / abs(sum(losing_pnl))`
- **Calmar ratio**: `annualized_return / max_drawdown_pct`

```python
# Signature sketch (not pseudocode -- actual signature)
class BacktestEngine:
    def execute(
        self,
        strategy: AgentStrategyBase,
        df: pd.DataFrame,
        initial_capital: float = 100_000.0,
    ) -> BacktestResult:
        ...

@dataclass
class BacktestResult:
    trades: list[BacktestTrade]
    equity_curve: list[dict[str, Any]]   # [{date: str, nav: float}]
    metrics: BacktestMetrics
```

#### File 9: `ranking.py` -- RankingService

```python
class RankingService:
    def compute_rankings(
        self, metrics_list: list[BacktestMetrics]
    ) -> list[BacktestMetrics]:
        """
        Normalize each metric across all agents using min-max scaling.
        Compute composite score:
          0.30 * norm(sharpe_ratio)
        + 0.20 * norm(total_return_pct)
        + 0.20 * norm(win_rate)
        + 0.15 * norm(-max_drawdown_pct)  # invert: lower DD = better
        + 0.15 * norm(profit_factor)

        Returns the list with ranking_score populated, sorted descending.
        """
        ...
```

#### File 10: `service.py` -- BacktestService

```python
class BacktestService:
    def __init__(
        self,
        repository: BacktestRepository,
        market_data: YFinanceMarketDataAdapter,
    ) -> None: ...

    async def run_backtest(self, request: BacktestRunRequest) -> BacktestRun:
        """
        1. Create run record (RUNNING)
        2. For each symbol: fetch OHLCV, execute engine, collect results
        3. Aggregate trades and metrics across symbols
        4. Save to DB
        5. Recompute rankings
        6. Update run status (COMPLETED)
        """
        ...

    async def get_rankings(
        self, sort_by: str = "ranking_score", order: str = "desc"
    ) -> list[BacktestRankingRow]:
        ...

    async def get_agent_results(self, agent_name: str) -> BacktestAgentDetail:
        ...

    async def get_agent_trades(
        self, agent_name: str, limit: int, offset: int, symbol: str | None
    ) -> dict:
        ...
```

### Test Plan (Phase 1)

```
tests/
  test_backtest_engine.py        # Unit: engine with a trivial always-buy strategy
  test_strategies.py             # Unit: each strategy on synthetic OHLCV data
  test_ranking.py                # Unit: ranking normalization with known inputs
```

1. **test_backtest_engine**: Create a synthetic 100-day DataFrame with known prices (linear uptrend). Use a stub strategy that buys on day 10 and sells on day 20. Assert trades list has exactly 1 trade with correct PnL. Assert equity curve starts at 100000 and ends higher.
2. **test_strategies**: For each of the 3 strategies, create a DataFrame that should trigger exactly 1 entry signal. Assert signal series contains exactly one `1`. For breakout: inject a day where Close > 20-day high and Volume > 2x avg.
3. **test_ranking**: Provide 3 mock BacktestMetrics with known sharpe/return/etc. Assert composite scores match hand-calculated values.

### Exit Criteria (Phase 1)

- `pytest tests/test_backtest_engine.py tests/test_strategies.py tests/test_ranking.py` passes.
- `BacktestEngine.execute()` returns correct trades and metrics for synthetic data.
- All 3 strategy classes produce non-trivial signals on real SPY 1-year data (manual verification).

---

## Phase 2: Remaining 4 Strategies + Repository + DB

**Scope**: Implement the remaining 4 strategies (VCP, dark pool, earnings momentum, iron condor), the PostgreSQL repository, and the DB schema.

**Duration**: 1 focused session

### Files to Create/Modify (11)

| # | File | Action |
|---|---|---|
| 1 | `backend/services/backtest/strategies/vcp_strategy.py` | CREATE |
| 2 | `backend/services/backtest/strategies/dark_pool_strategy.py` | CREATE |
| 3 | `backend/services/backtest/strategies/earnings_momentum_strategy.py` | CREATE |
| 4 | `backend/services/backtest/strategies/iron_condor_strategy.py` | CREATE |
| 5 | `backend/services/backtest/strategies/__init__.py` | MODIFY: register all 7 strategies |
| 6 | `backend/adapters/backtest_repository.py` | CREATE |
| 7 | `sql/backtest_schema.sql` | CREATE |
| 8 | `tests/test_vcp_strategy.py` | CREATE |
| 9 | `tests/test_dark_pool_strategy.py` | CREATE |
| 10 | `tests/test_earnings_momentum_strategy.py` | CREATE |
| 11 | `tests/test_iron_condor_strategy.py` | CREATE |

### Strategy Specifications

#### VCP Strategy (`vcp_strategy.py`)

```python
"""
Volatility Contraction Pattern:
- Compute weekly range (High - Low) over 3 consecutive weeks
- Entry: 3 consecutive narrowing ranges + volume below 50% of 20-day avg + breakout above range high
- Exit: 3R profit target or stop at lowest low of the contraction
"""
class VCPStrategy(AgentStrategyBase):
    def compute_indicators(self, df):
        # Weekly range: rolling 5-day (High.max - Low.min)
        df["range_w1"] = df["High"].rolling(5).max() - df["Low"].rolling(5).min()
        df["range_w2"] = df["range_w1"].shift(5)
        df["range_w3"] = df["range_w1"].shift(10)
        df["vol_avg_20"] = df["Volume"].rolling(20).mean()
        df["range_high"] = df["High"].rolling(15).max()
        df["range_low"] = df["Low"].rolling(15).min()
        return df

    def generate_signals(self, df):
        # Contraction: each week's range is tighter than the prior
        contraction = (
            (df["range_w1"] < df["range_w2"]) &
            (df["range_w2"] < df["range_w3"]) &
            df["range_w3"].notna()
        )
        volume_dry = df["Volume"] < 0.5 * df["vol_avg_20"]
        breakout = df["Close"] > df["range_high"].shift(1)

        signals = pd.Series(0, index=df.index)
        signals[contraction & volume_dry & breakout] = 1
        return signals
```

#### Dark Pool Follow-Through (`dark_pool_strategy.py`)

Since dark pool data is not available in yfinance, this strategy is **simulated** using unusually large single-bar volume as a proxy for institutional block prints.

```python
"""
Dark Pool proxy: detect bars with volume > 5x 20-day average (block-like activity).
Entry: day after 3+ consecutive high-volume bars at similar price level.
Exit: 5 trading days after entry or +3% profit, whichever comes first.
"""
class DarkPoolStrategy(AgentStrategyBase):
    def compute_indicators(self, df):
        df["vol_avg_20"] = df["Volume"].rolling(20).mean()
        df["high_vol"] = df["Volume"] > 5 * df["vol_avg_20"]
        # Count consecutive high-vol days in trailing 5-day window
        df["hv_count_5d"] = df["high_vol"].rolling(5).sum()
        # Price stability: range of closes in 5-day window < 2% of mean
        df["close_std_5d"] = df["Close"].rolling(5).std()
        df["close_mean_5d"] = df["Close"].rolling(5).mean()
        df["price_stable"] = df["close_std_5d"] < 0.02 * df["close_mean_5d"]
        return df

    def generate_signals(self, df):
        signals = pd.Series(0, index=df.index)
        entry = (df["hv_count_5d"] >= 3) & df["price_stable"] & df["hv_count_5d"].notna()
        signals[entry] = 1
        return signals
    # Engine handles 5-day time exit via max_hold_days in config
```

#### Earnings Momentum (`earnings_momentum_strategy.py`)

```python
"""
Gap-and-go after earnings:
- Entry: Open gaps up > 3% from prior close AND prior day volume > 2x 20-day avg
- Exit: End of day (same-day trade)
Note: Without actual earnings dates, we detect large gap-ups with volume surge
as a proxy for earnings events.
"""
class EarningsMomentumStrategy(AgentStrategyBase):
    def compute_indicators(self, df):
        df["prev_close"] = df["Close"].shift(1)
        df["gap_pct"] = (df["Open"] - df["prev_close"]) / df["prev_close"] * 100
        df["prev_volume"] = df["Volume"].shift(1)
        df["vol_avg_20"] = df["Volume"].rolling(20).mean().shift(1)
        return df

    def generate_signals(self, df):
        signals = pd.Series(0, index=df.index)
        entry = (
            (df["gap_pct"] > 3.0) &
            (df["prev_volume"] > 2 * df["vol_avg_20"]) &
            df["gap_pct"].notna() &
            df["vol_avg_20"].notna()
        )
        signals[entry] = 1
        # Same-day exit: also emit -1 on entry days (engine enters at Open, exits at Close)
        signals[entry] = 1  # engine handles same-day with max_hold_days=0
        return signals
```

#### Iron Condor (`iron_condor_strategy.py`)

```python
"""
Iron Condor simulation using OHLCV only:
- Use VIX as IV proxy (or compute 20-day realized vol)
- Entry: when 20-day realized vol > 25% annualized (high IV environment)
- Simulate selling a 20-delta strangle:
  - Short call at close + 1.5 * ATR(20)
  - Short put at close - 1.5 * ATR(20)
  - Collect premium = 2 * (0.02 * close) as simplified estimate
- P&L: premium collected minus max(0, close - call_strike, put_strike - close) at exit
- Exit: 5 trading days or when price exceeds strike +/- band
"""
class IronCondorStrategy(AgentStrategyBase):
    def get_config(self):
        return StrategyConfig(
            name="iron_condor",
            direction="both",  # non-directional
            max_positions=1,
            default_position_size_pct=5.0,
        )

    def compute_indicators(self, df):
        df["realized_vol"] = df["Close"].pct_change().rolling(20).std() * (252 ** 0.5) * 100
        df["atr_20"] = _atr(df, 20)
        return df

    def generate_signals(self, df):
        signals = pd.Series(0, index=df.index)
        # Enter when realized vol is elevated
        high_vol = (df["realized_vol"] > 25) & df["realized_vol"].notna()
        signals[high_vol] = 1
        return signals
    # Custom P&L logic handled via overridden methods in engine
```

#### Repository (`backtest_repository.py`)

Follows the exact same pattern as `PostgresSignalRepository` -- raw SQL via `sqlalchemy.text()`, async session, Pydantic model hydration.

```python
class BacktestRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def create_run(self, run: BacktestRun) -> BacktestRun: ...
    async def update_run_status(self, run_id: str, status: str, error: str | None = None) -> None: ...
    async def save_trades(self, trades: list[BacktestTrade]) -> None: ...
    async def save_metrics(self, metrics: BacktestMetrics) -> None: ...
    async def update_ranking_scores(self, updates: list[tuple[str, float]]) -> None: ...

    async def get_latest_run(self, agent_name: str) -> BacktestRun | None: ...
    async def get_latest_metrics_all(self) -> list[BacktestMetrics]: ...
    async def get_metrics_by_run(self, run_id: str) -> BacktestMetrics | None: ...
    async def get_trades_by_run(
        self, run_id: str, limit: int, offset: int, symbol: str | None
    ) -> tuple[list[BacktestTrade], int]: ...
```

### Test Plan (Phase 2)

1. Each of the 4 new strategies tested with synthetic data that triggers exactly 1 signal.
2. Repository tested with an in-memory SQLite or test PostgreSQL database.
3. Schema validated: `psql -f sql/backtest_schema.sql` runs idempotently.

### Exit Criteria (Phase 2)

- All 7 strategies registered in `STRATEGY_REGISTRY` and pass unit tests.
- Repository can create/read/update backtest runs, trades, metrics against PostgreSQL.
- `sql/backtest_schema.sql` is runnable and idempotent.

---

## Phase 3: API Endpoints + Integration

**Scope**: Wire the FastAPI router, dependency injection, and end-to-end integration test. Run a real backtest via the API.

**Duration**: 1 focused session

### Files to Create/Modify (6)

| # | File | Action |
|---|---|---|
| 1 | `backend/api/routers/backtest.py` | CREATE: 4 endpoints |
| 2 | `backend/api/dependencies.py` | MODIFY: add `get_backtest_service` |
| 3 | `backend/main.py` (or wherever routers are registered) | MODIFY: include backtest router |
| 4 | `data/cache/ohlcv/.gitkeep` | CREATE: cache directory |
| 5 | `tests/test_backtest_api.py` | CREATE: integration tests |
| 6 | `tests/test_backtest_service.py` | CREATE: service-level tests |

### Router Implementation

```python
# backend/api/routers/backtest.py
router = APIRouter(prefix="/api/backtest", tags=["backtest"])

@router.post("/run", status_code=202)
async def run_backtest(
    request: BacktestRunRequest,
    user: CurrentUser,
    service: BacktestService = Depends(get_backtest_service),
) -> dict:
    """Trigger a backtest run. Executes in a thread pool."""
    run = await service.run_backtest(request)
    return {
        "run_id": run.id,
        "agent_name": run.agent_name,
        "status": run.status.value,
        "symbols": run.symbol_list,
        "created_at": run.created_at.isoformat(),
    }

@router.get("/rankings")
async def get_rankings(
    user: CurrentUser,
    service: BacktestService = Depends(get_backtest_service),
    sort_by: str = Query("ranking_score"),
    order: str = Query("desc"),
) -> dict: ...

@router.get("/{agent_name}/results")
async def get_agent_results(
    agent_name: str,
    user: CurrentUser,
    service: BacktestService = Depends(get_backtest_service),
) -> dict: ...

@router.get("/{agent_name}/trades")
async def get_agent_trades(
    agent_name: str,
    user: CurrentUser,
    service: BacktestService = Depends(get_backtest_service),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    symbol: str | None = Query(None),
) -> dict: ...
```

### Dependency Addition

```python
# Add to backend/api/dependencies.py

def get_backtest_service(session: DbSession) -> BacktestService:
    from ..adapters.backtest_repository import BacktestRepository
    from ..services.backtest.service import BacktestService
    repo = BacktestRepository(session)
    market_data = get_market_data_adapter()
    return BacktestService(repo, market_data)
```

### Test Plan (Phase 3)

1. `test_backtest_api.py`: Use `httpx.AsyncClient` with the FastAPI test client. Test all 4 endpoints. Mock the `BacktestService` to return known data.
2. `test_backtest_service.py`: Integration test that runs `BacktestService.run_backtest()` against real yfinance data for `breakout_trader` on `SPY` for 6 months. Assert metrics are reasonable (Sharpe > -5, total_trades > 0).

### Exit Criteria (Phase 3)

- `curl -X POST localhost:8000/api/backtest/run -d '{"agent_name":"breakout_trader","symbols":["SPY"],"start_date":"2025-01-01","end_date":"2026-05-01"}'` returns 202 with a valid run_id.
- `curl localhost:8000/api/backtest/rankings` returns all agents with scores.
- `curl localhost:8000/api/backtest/breakout_trader/results` returns metrics + equity curve.
- All tests pass.

---

## Phase 4: Frontend Integration

**Scope**: TypeScript types, React Query hooks, and `AgentAttributionPanel` modification. Pure frontend -- no backend changes.

**Duration**: 1 focused session

### Files to Create/Modify (5)

| # | File | Action |
|---|---|---|
| 1 | `frontend/src/types/backtest.ts` | CREATE |
| 2 | `frontend/src/hooks/useBacktestRankings.ts` | CREATE |
| 3 | `frontend/src/lib/queryKeys.ts` | MODIFY: add 2 keys |
| 4 | `frontend/src/components/analytics/AgentAttributionPanel.tsx` | MODIFY: add ranking view |
| 5 | `frontend/src/components/shared/BacktestPanel.tsx` | MODIFY: wire to real API |

### AgentAttributionPanel Changes

The panel gets a toggle in the header: `LIVE | BACKTEST`.

- **LIVE mode** (default): current behavior using `useLiveFleet()`.
- **BACKTEST mode**: calls `useBacktestRankings()` and renders:
  - Rank column (1, 2, 3...)
  - Agent name
  - Sharpe ratio (color: green > 1.5, yellow > 0.5, red < 0.5)
  - Win rate (color: green > 60%, yellow > 45%, red < 45%)
  - Total return % (green/red based on sign)
  - Max drawdown % (always red)
  - Composite score as a progress bar (0-1 scale)
  - Click row to open agent detail (calls `useBacktestAgentResults`)

### BacktestPanel Changes

Replace the hardcoded `AGENTS` array with the 7 backtestable agent names. Wire the "Run Backtest" button to `useRunBacktest()` mutation. On success, invalidate rankings and show results from the API response.

### Test Plan (Phase 4)

1. Manual: toggle between LIVE and BACKTEST views, confirm data renders.
2. Verify React Query cache keys do not conflict (backtest rankings vs fleet).
3. Run `npm run typecheck` -- no TypeScript errors.

### Exit Criteria (Phase 4)

- `AgentAttributionPanel` renders backtest rankings with all columns when toggled.
- Clicking an agent shows expanded detail with metrics.
- `BacktestPanel` triggers real API calls and displays results.
- No TypeScript errors. No console errors.

---

## Summary

| Phase | Files Created | Files Modified | Total Touched | Mixes Apex+LWC+React? |
|---|---|---|---|---|
| Phase 1: Core Engine | 10 | 0 | 10 | No (Python only) |
| Phase 2: Strategies + DB | 9 | 2 | 11 | No (Python + SQL) |
| Phase 3: API + Integration | 4 | 2 | 6 | No (Python only) |
| Phase 4: Frontend | 2 | 3 | 5 | No (TypeScript only) |

All phases are under the 15-file limit. No phase mixes backend and frontend concerns (Phase 4 is pure frontend).

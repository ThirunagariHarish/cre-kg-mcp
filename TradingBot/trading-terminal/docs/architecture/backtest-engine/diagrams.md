# Backtesting Engine -- Diagrams

---

## 1. System Component Diagram

```mermaid
graph TB
    subgraph "Frontend (React + Vite)"
        AAP[AgentAttributionPanel<br/>Toggle: Live / Backtest]
        BTP[BacktestPanel<br/>Trigger Runs]
        RQH[useBacktestRankings<br/>React Query Hook]
        RQM[useBacktestRun<br/>Mutation Hook]
    end

    subgraph "FastAPI Backend (:8000)"
        subgraph "API Layer"
            R1["POST /api/backtest/run"]
            R2["GET /api/backtest/rankings"]
            R3["GET /api/backtest/{agent}/results"]
            R4["GET /api/backtest/{agent}/trades"]
        end

        subgraph "Service Layer"
            BS[BacktestService<br/>Orchestrator]
            BE[BacktestEngine<br/>Vectorized Simulator]
            RS[RankingService<br/>Composite Score Calculator]
        end

        subgraph "Strategy Layer"
            ASB[AgentStrategyBase<br/>Abstract Class]
            S1[BreakoutStrategy]
            S2[AlbertProStrategy]
            S3[VCPStrategy]
            S4[DarkPoolStrategy]
            S5[EarningsMomentumStrategy]
            S6[IronCondorStrategy]
            S7[GapExecutorStrategy]
        end

        subgraph "Data Layer"
            BR[BacktestRepository<br/>PostgreSQL]
            YFA[YFinanceMarketDataAdapter<br/>Historical OHLCV]
        end
    end

    subgraph "Storage"
        PG[(PostgreSQL<br/>backtest_runs<br/>backtest_trades<br/>backtest_metrics)]
        CACHE[/Local Parquet Cache<br/>data/cache/ohlcv/]
    end

    AAP --> RQH
    BTP --> RQM
    RQH --> R2
    RQH --> R3
    RQM --> R1

    R1 --> BS
    R2 --> RS
    R3 --> BR
    R4 --> BR

    BS --> BE
    BS --> BR
    BS --> YFA
    BS --> RS

    BE --> ASB
    ASB --> S1
    ASB --> S2
    ASB --> S3
    ASB --> S4
    ASB --> S5
    ASB --> S6
    ASB --> S7

    BR --> PG
    YFA --> CACHE
```

---

## 2. Backtest Run Sequence Diagram

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as POST /api/backtest/run
    participant BS as BacktestService
    participant YF as YFinanceAdapter
    participant BE as BacktestEngine
    participant STR as AgentStrategy
    participant BR as BacktestRepository
    participant RS as RankingService

    FE->>API: {agent_name, symbols, start_date, end_date}
    API->>BS: run_backtest(request)
    BS->>BR: create_run(agent_name, symbols, start_date, end_date, status="RUNNING")
    BR-->>BS: run_id

    loop For each symbol
        BS->>YF: get_ohlcv(symbol, period="2y", interval="1d")
        YF-->>BS: DataFrame[Date, Open, High, Low, Close, Volume]
        BS->>BE: execute(strategy, df, initial_capital=100000)
        BE->>STR: generate_signals(df) -> Series[1, -1, 0]
        STR-->>BE: signal_series

        Note over BE: Walk forward through signals:<br/>1 = enter long, -1 = exit, 0 = hold<br/>Apply stop loss, profit target per strategy<br/>Track equity curve, trades, drawdown

        BE-->>BS: BacktestResult{trades, equity_curve, metrics}
        BS->>BR: save_trades(run_id, trades)
        BS->>BR: save_metrics(run_id, metrics)
    end

    BS->>RS: recompute_rankings()
    RS->>BR: get_all_latest_metrics()
    BR-->>RS: List[BacktestMetrics]

    Note over RS: For each metric:<br/>normalize to [0,1] via min-max<br/>composite = 0.30*sharpe + 0.20*return<br/>+ 0.20*winrate + 0.15*(-drawdown)<br/>+ 0.15*profit_factor

    RS->>BR: update_ranking_scores(rankings)
    BS->>BR: update_run_status(run_id, status="COMPLETED")
    BS-->>API: {run_id, status, metrics_summary}
    API-->>FE: 200 OK
```

---

## 3. Data Flow: Rankings Query

```mermaid
sequenceDiagram
    participant AAP as AgentAttributionPanel
    participant RQ as React Query
    participant API as GET /api/backtest/rankings
    participant RS as RankingService
    participant BR as BacktestRepository

    AAP->>RQ: useQuery(['backtest', 'rankings'])
    RQ->>API: GET /api/backtest/rankings
    API->>BR: get_latest_metrics_all_agents()
    BR-->>API: List[{agent_name, sharpe, sortino, win_rate, ..., ranking_score}]

    Note over API: Sort by ranking_score DESC<br/>Add rank ordinal (1, 2, 3...)

    API-->>RQ: [{rank: 1, agent_name: "vcp_setups_trader", ...}, ...]
    RQ-->>AAP: Render ranking table
```

---

## 4. Strategy Signal Flow (per agent)

```mermaid
graph LR
    subgraph "Input"
        DF[DataFrame<br/>Date | O | H | L | C | V]
    end

    subgraph "Strategy: generate_signals()"
        IND[Compute Indicators<br/>SMA, RSI, ATR, etc.]
        COND[Apply Entry/Exit<br/>Conditions]
        SIG[Signal Series<br/>1=BUY, -1=SELL, 0=HOLD]
    end

    subgraph "BacktestEngine: execute()"
        POS[Position Tracker<br/>entry_price, qty, stop, target]
        EQ[Equity Curve<br/>daily NAV]
        TL[Trade Log<br/>entry, exit, pnl]
        MET[Metrics Calculator<br/>Sharpe, Sortino, DD, etc.]
    end

    DF --> IND --> COND --> SIG
    SIG --> POS --> EQ
    POS --> TL
    EQ --> MET
```

---

## 5. Database Entity Relationship

```mermaid
erDiagram
    backtest_runs {
        uuid id PK
        varchar agent_name
        varchar symbols
        date start_date
        date end_date
        varchar status
        float initial_capital
        timestamp created_at
        timestamp completed_at
    }

    backtest_trades {
        uuid id PK
        uuid run_id FK
        varchar symbol
        varchar direction
        date entry_date
        date exit_date
        float entry_price
        float exit_price
        float quantity
        float pnl
        float pnl_pct
        varchar exit_reason
        timestamp created_at
    }

    backtest_metrics {
        uuid id PK
        uuid run_id FK
        varchar agent_name
        float total_return_pct
        float sharpe_ratio
        float sortino_ratio
        float max_drawdown_pct
        float win_rate
        float profit_factor
        float calmar_ratio
        int total_trades
        float avg_trade_pnl
        float avg_win
        float avg_loss
        float ranking_score
        timestamp created_at
    }

    backtest_runs ||--o{ backtest_trades : "has many"
    backtest_runs ||--|| backtest_metrics : "has one"
```

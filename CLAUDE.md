# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

The active codebase lives in `Legacy/`. The repo root is otherwise empty (no source outside `Legacy/`).

```
Legacy/
├── core/             # Shared infrastructure: BaseAgent, AppConfig, StateManager, safety, RL loop
├── agents_impl/      # 140+ agent implementations (one class per strategy)
├── agents/           # 230+ live agent instances (each: config.json + logs/ + trades/)
├── scripts/          # 257 runnable entry points (run_*.py, launch_all.py, web_dashboard.py)
├── services/         # Standalone microservices: accountability, position_manager, signal_router
├── schemas/          # Pydantic v2 data contracts (trade, market, RL, message schemas)
├── shared/           # File-based IPC: premarket_analysis.json, market_context.json, watchlist.json
├── tests/            # 340+ test files: unit/, integration/, agents_impl/, e2e/, fixtures/
├── web/v2/           # React dashboard source (pnpm)
├── static/v2/        # Built React bundle
├── k8s/              # Kustomize overlays + Doppler/External Secrets manifests
├── helm/             # Helm charts for production
├── infra/            # Prometheus, Grafana, ArgoCD, logging configs
├── db/               # trades.db (SQLite — all trade history)
├── docs/             # Runbooks, deployment guide, troubleshooting, system manual
└── mobile_app/       # React Native app
```

## Commands

All commands run from `Legacy/` unless noted.

### Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in credentials
```

### Running agents

```bash
# Pre-market analysis — run at ~8:45 AM ET before market open
python scripts/run_premarket.py

# Launch ALL agents via tmux (reads agents/registry.json, one window per agent)
python scripts/launch_all.py
tmux attach -t selfagentbot

# Run a single agent
python scripts/run_trade_whisperer.py
python scripts/run_breakout_trader.py
# ... any of the 257 scripts/run_*.py scripts

# Web dashboard (FastAPI on port 8080)
python -m scripts.web_dashboard

# 30-minute background market monitor
python scripts/run_marketwatch.py

# Backtesting
python scripts/run_backtest.py --agent breakout_trader --start 2024-01-01 --end 2024-06-30
python scripts/run_all_backtests.py   # batch all agents
```

### Docker (local dev — 15 services)
```bash
make build    # docker compose build
make up       # docker compose up -d
make down     # docker compose down
make logs     # docker compose logs -f
make status   # docker compose ps
```

### Kubernetes
```bash
make k8s-local-setup   # install k3d + create cluster
make k8s-build         # docker build -t selfagentbot:latest .
make k8s-apply         # kubectl apply -k k8s/
make k8s-status        # kubectl get pods -n trading
make k8s-logs          # kubectl logs -f (prompts for agent name)
make k8s-restart       # kubectl rollout restart
```

### Testing
```bash
pytest tests/ -q                                      # all unit tests
pytest tests/ -m integration                          # integration tests only
pytest tests/test_backtest_engine.py -v               # single file
pytest tests/test_backtest_engine.py::test_limit_order_fills -vv  # single test
pytest tests/ --cov=core --cov=agents_impl --cov-report=html
```

### Linting & formatting
```bash
black core/ agents_impl/ scripts/ services/   # line length 100
ruff check core/ agents_impl/ scripts/        # E9, F63, F7, F82 only
mypy core/ agents_impl/ --python-version=3.11
```

### Schema export (CI gate)
```bash
make export-theme-schema   # regenerate JSON Schema from Pydantic models
make check-theme-schema    # verify parity (fails CI if out of sync)
```

## Architecture

### Signal flow (Discord → execution)

```
Discord channel (WebSocket)
  → TradeWhisperer agent (agents_impl/trade_whisperer/)
  → Claude LLM decodes free-form message → structured Signal
  → TechnicalAnalystAgent gates on EMA/RSI/MACD/OI
      ├── APPROVE → RobinhoodAgent (limit order, 15-second monitor)
      └── REJECT  → logged with reason
  → agents/{name}/trades/YYYY-MM-DD.json  (audit trail)
  → db/trades.db (SQL history)
```

### File-based IPC (no Redis required by default)

All inter-agent communication goes through JSON files in `shared/` and `agents/`. Writes are atomic (temp-file + rename) via `core/state_manager.py::StateManager.atomic_write()`. Watchdog polls for changes using inotify/kqueue. Redis is optional (services/state_sync/ syncs files ↔ Redis when enabled).

### Reinforcement learning loop (EOD)

`agents_impl/eod_evaluator/` triggers at 4:30 PM ET:
1. Reads last 7 days of trade JSON files
2. Calculates win rate by signal type, runs loss autopsy
3. Emits up to 3 `ParameterChange` records (confidence threshold, indicator weights)
4. Auto-applies changes within hard limits; defers position-sizing to human review
5. Writes `rl/evaluations.json` + updates per-agent `config.json` + `memory.json`

### Configuration layers

| Layer | Source | Scope |
|---|---|---|
| App-wide | `.env` → `core/config.py::AppConfig` | All agents share |
| Per-agent | `agents/{name}/config.json` → `core/config.py::AgentConfig` | One agent |
| Per-channel | `agents/{name}/config.json` → `ChannelConfig` | One Discord channel |

`AgentConfig` is a Pydantic v2 model; validate with `AgentConfig.model_validate(...)`.

### State storage hierarchy

| Data | Location | Format |
|---|---|---|
| Today's trades | `agents/{name}/trades/YYYY-MM-DD.json` | JSON |
| All trade history | `db/trades.db` | SQLite |
| RL evaluations | `agents/{name}/rl/evaluations.json` | JSON |
| Market context | `shared/market_context.json` | JSON (updated every 30 min) |
| Pre-market bias | `shared/premarket_analysis.json` | JSON (written at 8:45 AM) |
| Active watchlist | `shared/watchlist.json` | JSON |
| Agent memory | `agents/{name}/memory.json` | JSON (sized to fit Claude context) |

## Key abstractions

- **`core/base_agent.py::BaseAgent`** — abstract base all agents inherit; provides `run()`, `stop()`, heartbeat, structured logging
- **`core/config.py`** — `AppConfig` (from `.env`), `AgentConfig` (from per-agent JSON)
- **`core/state_manager.py::StateManager`** — atomic file writes, crash-safe reads
- **`core/safety/`** — kill-switch, PDT rule enforcement, max-loss limiter
- **`schemas/`** — authoritative Pydantic v2 models; never hand-write JSON contracts

## Safety controls (always active unless explicitly overridden)

- **`PAPER_TRADING_MODE=true`** (default) — simulates all orders; set to `false` only for live trading
- **`MAX_DAILY_LOSS_DOLLARS=500`** — automatic kill-switch if daily loss exceeds limit
- **`MAX_POSITION_SIZE_DOLLARS=200`** — hard cap per position
- **PDT enforcement** — 3-trade limit per rolling 5-day window (enforced in `core/safety/`)
- **Trusted author whitelist** — `DISCORD_TRUSTED_AUTHOR_IDS` gates which Discord users can trigger trades
- **Signal deduplication** — duplicate signals within the same session are silently dropped

## Key docs in `Legacy/docs/`

- `RUNBOOK.md` — daily startup sequence, monitoring checklist, emergency stop procedure
- `DEPLOYMENT_GUIDE.md` — first-time setup, going-live checklist
- `TROUBLESHOOTING.md` — 10 most common failure modes and fixes
- `SYSTEM_MANUAL.md` — deep-dive architecture, ADRs, component diagrams

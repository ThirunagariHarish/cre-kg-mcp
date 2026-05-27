# Trading Monk — AI Trading Terminal

A Bloomberg-style terminal for monitoring AI trading agents, analyzing signals, and managing positions — built with React 18 + TypeScript.

![TypeScript](https://img.shields.io/badge/TypeScript-5.x-blue) ![React](https://img.shields.io/badge/React-18-61dafb) ![Vite](https://img.shields.io/badge/Vite-5-646cff) ![Tests](https://img.shields.io/badge/tests-77%20passing-brightgreen)

---

## Features

### 8 Workspace Tabs
| Tab | Description |
|---|---|
| **Positions** | Live portfolio with unrealized P&L, day P&L, weight |
| **Agents** | 23-agent fleet — status, signals, win rate, P&L sparklines |
| **Orders** | Order blotter with fill tracking and status badges |
| **Signals** | Signal feed from Discord, Telegram, AI, algorithms |
| **Chart** | Candlestick + volume, order book L2, options chain |
| **Analytics** | Equity curve, drawdown, attribution, sector exposure, P&L calendar |
| **Intelligence** | Market regime, confluence, options flow, dark pool, news, social buzz |
| **Backtest** | Strategy backtesting with Brownian-motion equity simulation |

### Charts
- TradingView `lightweight-charts` v5 candlestick with volume histogram
- Order book L2 (live depth bars, 500ms mock updates)
- Options chain (two-sided calls/puts, ATM detection, IV coloring)
- GEX chart (gamma exposure SVG bars)
- IV gauge (circular SVG arc, rank/percentile)
- Volume profile (POC, VAH, VAL, VWAP)

### Analytics
- Equity curve (recharts ComposedChart, benchmark overlay)
- Drawdown underwater chart with high-watermark
- Agent attribution (per-agent P&L bars with sparklines)
- Sector exposure donut chart
- P&L calendar (GitHub contribution-style grid)
- Performance metrics (Sharpe, Sortino, win rate, expectancy)

### Intelligence
- Market regime badge — BULL_QUIET / BULL_VOLATILE / BEAR_QUIET / BEAR_VOLATILE / NEUTRAL
- Confluence panel — 3+ agent agreement signals
- Options flow feed — SWEEP/BLOCK prints with premium filter
- Dark pool feed — large prints with VWAP comparison
- News feed — Reuters, Bloomberg, SEC with sentiment
- Social buzz (WSB mentions, sentiment gauge)
- Short squeeze scanner
- Congress/insider trades
- Approvals inbox (keyboard shortcuts: A approve, R reject)
- Audit trail with pagination and type filters

### Agent Management
- Fleet overview with sparklines and dependency graph
- 4-step creation wizard (template → configure → risk → review)
- Per-agent: log viewer, config editor, timeline, status modal

### Advanced Trading
- Equity / Options / Spread ticket switcher in right rail
- Position sizer with Kelly criterion
- Risk policy editor with utilization bars
- Pre-trade risk check modal on every submit
- Alert creator (price, P&L, technical, news alerts)
- Paper / Live mode toggle with 5-second countdown + CONFIRM gate

### UX
- Command palette `⌘K` with 12+ navigation shortcuts
- Right-click context menus on positions and watchlist rows
- Settings gear → Risk Policy Editor modal
- Bloomberg dark aesthetic: `#000000` bg, `#ff6600` orange, IBM Plex Mono

---

## Tech Stack

| Layer | Library |
|---|---|
| Framework | React 18 |
| Language | TypeScript 5 |
| Build | Vite 5 |
| Styling | Tailwind CSS v3 |
| State | Zustand (with `persist` middleware) |
| Data fetching | @tanstack/react-query v5 |
| Charts | lightweight-charts v5, recharts |
| UI primitives | Radix UI (Dialog, Tabs, Select, Toast) |
| Icons | lucide-react |
| Dates | date-fns |
| Virtualization | @tanstack/react-virtual |
| Testing | Vitest + @testing-library/react |

---

## Quick Start

```bash
# Install dependencies
npm install

# Copy env and set your token
cp .env.example .env.local

# Run dev server
npm run dev
# → http://localhost:5173
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8080` | SelfAgentBot backend URL |
| `VITE_WS_URL` | `ws://localhost:8080` | WebSocket endpoint |
| `VITE_API_TOKEN` | — | Bearer token for API auth |
| `VITE_ENV` | `development` | Environment name |
| `VITE_MOCK_DATA` | `true` | Set to `false` to enable live backend polling |

---

## Project Structure

```
src/
├── components/
│   ├── agents/        # AgentsPanel, wizard, log viewer, dependency graph
│   ├── ai/            # AI recommendation panel and card
│   ├── analytics/     # Equity curve, drawdown, attribution, metrics
│   ├── charts/        # CandlestickChart, OrderBookL2, OptionsChain, GEX, IV
│   ├── intelligence/  # Regime, confluence, flow, news, approvals, audit
│   ├── layout/        # GlobalCommandBar, TerminalShell, console
│   ├── market/        # WatchlistPanel, MarketDataGrid, PriceCell
│   ├── risk/          # RiskPanel, RiskPolicyEditor, PreTradeRiskCheck
│   ├── shared/        # CommandPalette, AlertRail, VirtualTable, BacktestPanel
│   ├── signals/       # SignalFeed, SignalCard, SignalBadge
│   └── trading/       # TradeTicket, OptionsTradeTicket, OrderBlotter, PositionsGrid
├── hooks/             # useLiveFleet, useLivePortfolio, useLiveSignals, useSSE…
├── lib/
│   ├── api/           # client.ts (fetch wrapper), endpoints.ts
│   ├── queryClient.ts
│   └── queryKeys.ts
├── stores/            # terminalStore, marketStore (Zustand)
├── types/             # agents, ai, market, orders, portfolio, risk, signals
└── utils/             # formatters
```

---

## Backend Integration

All 9 live-data hooks activate automatically when `VITE_MOCK_DATA=false`:

```env
VITE_MOCK_DATA=false
VITE_API_BASE_URL=http://localhost:8080
VITE_API_TOKEN=your-token
```

The Vite dev proxy forwards `/api/*` → `localhost:8080` and `/ws` → `ws://localhost:8080`. The backend is a SelfAgentBot FastAPI service exposing REST endpoints and 6 SSE streams.

---

## Available Scripts

```bash
npm run dev       # Dev server at localhost:5173
npm run build     # Production build → dist/
npm run preview   # Preview production build
npm run test      # Run vitest (77 tests)
npx tsc --noEmit  # Type check
```

---

## License

Private repository — all rights reserved.

export const API = {
  // Auth
  login: '/auth/login',

  // Signals
  signalFeed: '/api/signals/feed',
  signalIngest: '/api/signals/ingest',
  signals: '/api/signals/',

  // Orders
  orders: '/api/orders',
  order: (id: string) => `/api/orders/${encodeURIComponent(id)}`,

  // Portfolio / Positions
  portfolioSummary: '/api/portfolio/summary',
  portfolioPositions: '/api/portfolio/positions',
  equityCurve: (range: string) => `/api/portfolio/equity-curve?range=${range}`,
  positions: '/api/positions',

  // Market data
  quotes: (symbols: string) => `/api/market/quotes?symbols=${encodeURIComponent(symbols)}`,
  quote: (symbol: string) => `/api/market/quote/${encodeURIComponent(symbol)}`,
  marketSearch: (q: string) => `/api/market/search?q=${encodeURIComponent(q)}`,
  marketData: (symbol: string) => `/api/market/data/${encodeURIComponent(symbol)}`,
  marketIndices: '/api/market/indices',
  marketNews: '/api/market/news',
  shortInterest: (symbol: string) => `/api/market/short-interest/${encodeURIComponent(symbol)}`,
  marketOhlcv: (symbol: string) => `/api/market/ohlcv/${encodeURIComponent(symbol)}`,

  // Risk
  riskStatus: '/api/risk/status',
  riskPolicy: '/api/risk/policy',
  emergencyStopActivate: '/api/risk/emergency-stop',
  emergencyStopDeactivate: '/api/risk/emergency-stop',

  // AI
  aiRecommend: '/api/ai/recommend',

  // Audit
  auditLog: '/api/audit',

  // Watchlist
  watchlist: '/api/watchlist',
  watchlistItem: (symbol: string) => `/api/watchlist/${encodeURIComponent(symbol)}`,

  // Alerts
  alertRules: '/api/alerts/rules',
  alertRule: (id: string) => `/api/alerts/rules/${encodeURIComponent(id)}`,

  // System
  health: '/health',

  // WebSocket
  ws: '/ws',

  // Agents (used by AgentsPanel and fleet hooks)
  fleet: '/api/fleet',
  agentStart: (name: string) => `/api/agent/${encodeURIComponent(name)}/start`,
  agentStop: (name: string) => `/api/agent/${encodeURIComponent(name)}/stop`,
  agentRestart: (name: string) => `/api/agent/${encodeURIComponent(name)}/restart`,
  agentLogs: (name: string) => `/api/agent/${encodeURIComponent(name)}/logs`,
  agentTimeline: (name: string) => `/api/agent/${encodeURIComponent(name)}/timeline`,
  agentConfig: (name: string) => `/api/agent/${encodeURIComponent(name)}/inspect`,

  // Approvals (used by useApprovals hook and AgentsPanel)
  approvals: '/api/approvals',
  approveSignal: (id: string) => `/api/approvals/${encodeURIComponent(id)}/approve`,
  rejectSignal: (id: string) => `/api/approvals/${encodeURIComponent(id)}/reject`,

  // Market regime (used by useMarketRegime hook)
  marketRegime: '/api/market-direction',

  // Robinhood Execution Agent
  robinhoodStatus: '/api/robinhood/status',
  robinhoodPositions: '/api/robinhood/positions',
  robinhoodExecute: '/api/robinhood/execute',
  robinhoodClose: (ticker: string) => `/api/robinhood/close/${encodeURIComponent(ticker)}`,

  // Backtest Engine
  backtestRankings: '/api/backtest/rankings',
  backtestResults: (agentId: string) => `/api/backtest/${encodeURIComponent(agentId)}/results`,
  backtestRun: '/api/backtest/run',

  // Options
  optionsExpiries: (symbol: string) => `/api/market/options/${encodeURIComponent(symbol)}/expiries`,
  optionsChain: (symbol: string) => `/api/market/options/${encodeURIComponent(symbol)}/chain`,
  optionsIvTerm: (symbol: string) => `/api/market/options/${encodeURIComponent(symbol)}/iv-term`,
  marketCorrelation: '/api/market/correlation',
} as const

/**
 * Centralised React Query key factory.
 *
 * Keys are tuples so React Query can match sub-trees for invalidation.
 * e.g. invalidating ['agent', 'foo'] will also invalidate
 *      ['agent', 'foo', 'logs'].
 */

export const QK = {
  fleet: ['fleet'] as const,
  agent: (name: string) => ['agent', name] as const,
  agentLogs: (name: string) => ['agent', name, 'logs'] as const,
  portfolio: ['portfolio'] as const,
  trades: ['trades'] as const,
  signalFeed: ['signal-feed'] as const,
  riskStatus: ['risk-status'] as const,
  quote: (symbol: string) => ['quote', symbol] as const,
  bars: (symbol: string, tf: string) => ['bars', symbol, tf] as const,
  optionChain: (symbol: string) => ['option-chain', symbol] as const,
  confluence: ['confluence'] as const,
  marketRegime: ['market-regime'] as const,
  optionsFlow: ['options-flow'] as const,
  darkPool: ['dark-pool'] as const,
  indices: ['indices'] as const,
  news: (symbols?: string) => ['news', symbols ?? ''] as const,
  shortInterest: (symbol: string) => ['short-interest', symbol] as const,
  ohlcv: (symbol: string, period: string, interval: string) => ['ohlcv', symbol, period, interval] as const,
  newsLegacy: ['news'] as const,
  pnlSummary: ['pnl-summary'] as const,
  pnlHistory: ['pnl-history'] as const,
  journalToday: ['journal', 'today'] as const,
  agentAttribution: ['agent-attribution'] as const,
  approvals: ['approvals'] as const,
  auditLog: ['audit-log'] as const,
  gex: (symbol: string) => ['gex', symbol] as const,
  ivRank: (symbol: string) => ['iv-rank', symbol] as const,
} as const

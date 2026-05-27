/* ============================================================
   Portfolio Types
   ============================================================ */

export interface Position {
  symbol: string
  quantity: number
  side: 'LONG' | 'SHORT'
  avgCostBasis: number
  currentPrice: number
  marketValue: number
  unrealizedPnl: number
  unrealizedPnlPercent: number
  dayPnl: number
  dayPnlPercent: number
  totalPnl: number
  totalPnlPercent: number
  weight: number // % of portfolio
  openedAt: number // unix ms
  lastUpdated: number
}

export interface Portfolio {
  id: string
  mode: 'PAPER' | 'LIVE'
  cashBalance: number
  equityValue: number
  totalValue: number
  dayPnl: number
  dayPnlPercent: number
  totalPnl: number
  totalPnlPercent: number
  positions: Position[]
  positionCount: number
  buyingPower: number
  timestamp: number
}

export interface PnLSummary {
  date: string
  realizedPnl: number
  unrealizedPnl: number
  totalPnl: number
  tradeCount: number
  winCount: number
  lossCount: number
  winRate: number
  avgWin: number
  avgLoss: number
  profitFactor: number
  maxDrawdown: number
}

export interface PnLDataPoint {
  timestamp: number
  equity: number
  dayPnl: number
  cumulativePnl: number
}

export interface Trade {
  id: string
  orderId: string
  symbol: string
  side: 'BUY' | 'SELL'
  quantity: number
  price: number
  value: number
  commission: number
  realizedPnl?: number
  timestamp: number
  mode: 'PAPER' | 'LIVE'
}

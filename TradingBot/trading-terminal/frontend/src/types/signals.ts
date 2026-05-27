/* ============================================================
   Signal Types
   ============================================================ */

export type SignalDirection = 'BUY' | 'SELL' | 'HOLD' | 'WATCH'
export type SignalSource = 'DISCORD' | 'TELEGRAM' | 'MANUAL' | 'AI' | 'ALGORITHM' | 'NEWS'
export type SignalStatus = 'PENDING' | 'ANALYZED' | 'APPROVED' | 'REJECTED' | 'EXECUTED' | 'EXPIRED'
export type ConfidenceLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'

export interface Signal {
  id: string
  source: SignalSource
  sourceChannel?: string
  rawMessage: string
  ticker: string
  direction: SignalDirection
  confidence?: number // 0-100
  confidenceLevel?: ConfidenceLevel
  status: SignalStatus
  receivedAt: number // unix ms
  analyzedAt?: number
  executedAt?: number
  expiresAt?: number
  price?: number
  targetPrice?: number
  stopLoss?: number
  takeProfit?: number
  timeframe?: string
  tags?: string[]
  notes?: string
  aiRecommendationId?: string
}

export interface ParsedSignal {
  id: string
  rawSignalId: string
  ticker: string
  direction: SignalDirection
  entryPrice?: number
  stopLoss?: number
  takeProfit?: number[]
  timeframe?: string
  confidence?: number
  reasoning?: string
  keyFactors?: string[]
  risks?: string[]
  parsedAt: number
  parser: string
  parserVersion?: string
}

export interface TradeIdea {
  id: string
  signalId?: string
  ticker: string
  direction: SignalDirection
  suggestedEntry: number
  suggestedSize?: number
  suggestedSizePercent?: number
  stopLoss?: number
  targetPrice?: number
  riskReward?: number
  confidence?: number
  thesis: string
  risks?: string[]
  timeframe?: string
  createdAt: number
  expiresAt?: number
  status: 'ACTIVE' | 'EXECUTED' | 'EXPIRED' | 'DISMISSED'
}

export interface SignalFilters {
  direction?: SignalDirection[]
  source?: SignalSource[]
  status?: SignalStatus[]
  confidenceMin?: number
  ticker?: string
  fromDate?: number
  toDate?: number
}

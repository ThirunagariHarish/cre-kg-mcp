/* ============================================================
   AI Recommendation Types
   ============================================================ */

export type ConfidenceLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'
export type AIAction = 'BUY' | 'SELL' | 'HOLD' | 'WATCH' | 'AVOID'
export type SentimentLabel = 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'MIXED'

export interface AIRecommendation {
  id: string
  signalId?: string
  ticker: string
  action: AIAction
  confidence: number              // 0-100
  confidenceLevel: ConfidenceLevel
  sentiment: SentimentLabel
  thesis: string                  // Main recommendation thesis
  keyFactors: string[]            // Bullish/bearish factors
  risks: string[]                 // Key risks
  catalysts?: string[]            // Near-term catalysts
  suggestedEntry?: number
  suggestedStopLoss?: number
  suggestedTargetPrice?: number
  suggestedPositionSizePercent?: number
  timeframe?: string              // "1D", "1W", "1M", etc.
  modelName: string               // "claude-3-5-sonnet", etc.
  modelVersion?: string
  promptTokens?: number
  completionTokens?: number
  generatedAt: number             // unix ms
  expiresAt?: number
  disclaimer: string              // Always show "NOT FINANCIAL ADVICE"
}

export interface AIAnalysisRequest {
  signalId: string
  ticker: string
  rawMessage: string
  currentPrice?: number
  portfolioContext?: {
    existingPosition?: number
    availableCash?: number
    portfolioRisk?: number
  }
}

export interface AIInsight {
  id: string
  ticker?: string
  type: 'MARKET_SUMMARY' | 'SECTOR_ANALYSIS' | 'SIGNAL_ANALYSIS' | 'RISK_ALERT' | 'OPPORTUNITY'
  title: string
  summary: string
  details?: string
  sentiment?: SentimentLabel
  confidence?: number
  relevantSymbols?: string[]
  generatedAt: number
  modelName: string
}

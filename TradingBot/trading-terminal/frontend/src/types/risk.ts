/* ============================================================
   Risk Types
   ============================================================ */

export type RiskDecision = 'ALLOW' | 'BLOCK' | 'WARN' | 'REVIEW'
export type RiskBreachSeverity = 'INFO' | 'WARNING' | 'CRITICAL'

export interface RiskPolicy {
  id: string
  name: string
  description: string
  enabled: boolean
  // Position limits
  maxPositionSizePercent: number  // % of portfolio
  maxSinglePositionValue: number  // absolute $
  maxPositionCount: number
  // Loss limits
  maxDailyLossPercent: number     // % of portfolio
  maxDailyLossAbsolute: number    // absolute $
  maxDrawdownPercent: number
  // Order limits
  maxOrderValue: number
  maxOrderQuantity: number
  // Concentration limits
  maxSectorExposurePercent: number
  maxSymbolExposurePercent: number
  // Kill switch
  killSwitchEnabled: boolean
  killSwitchDailyLossThreshold: number
  updatedAt: number
}

export interface RiskMetrics {
  totalExposure: number
  totalExposurePercent: number   // % of portfolio
  netExposure: number
  longExposure: number
  shortExposure: number
  dailyPnl: number
  dailyPnlPercent: number
  dailyLossUsedPercent: number   // 0-100 %
  maxDrawdown: number
  maxDrawdownPercent: number
  openPositionCount: number
  varDaily?: number              // Value at Risk (daily)
  sharpeRatio?: number
  timestamp: number
}

export interface RiskBreach {
  id: string
  severity: RiskBreachSeverity
  rule: string
  message: string
  value: number
  threshold: number
  timestamp: number
  resolved: boolean
  resolvedAt?: number
}

export interface RiskStatus {
  killSwitchActive: boolean
  killSwitchActivatedAt?: number
  killSwitchActivatedBy?: string
  isHealthy: boolean
  metrics: RiskMetrics
  breaches: RiskBreach[]
  policy: RiskPolicy
  lastUpdated: number
}

export interface RiskCheckResult {
  orderId?: string
  symbol: string
  quantity: number
  estimatedValue: number
  decision: RiskDecision
  reasons: string[]
  warnings: string[]
  checkedAt: number
}

export interface KillSwitchEvent {
  activatedAt: number
  activatedBy: 'USER' | 'SYSTEM' | 'RISK_ENGINE'
  reason: string
  portfolioValueAtActivation: number
  openPositionsCount: number
}

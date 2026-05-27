/* ============================================================
   Agent Types
   ============================================================ */

export type AgentStatus = 'RUNNING' | 'PAUSED' | 'STOPPED' | 'ERROR' | 'IDLE'
export type AgentCategory = 'ALGORITHM' | 'DISCORD' | 'AI' | 'DATA' | 'PORTFOLIO' | 'OPTIONS'
export type TradingMode = 'aggressive' | 'moderate' | 'conservative' | 'paper'

export interface AgentConfig {
  name: string
  description?: string
  notes?: string
  signal_source?: string
  scan_interval_seconds?: number
  confidence_threshold?: number
  trading_mode?: TradingMode
  stop_loss_pct?: number
  profit_target_pct?: number
  max_daily_trades?: number
  broker?: string
  discord_channels?: Array<{ channel_id: number; channel_name: string }>
}

export interface AgentMetrics {
  totalSignals: number
  executedTrades: number
  winCount: number
  lossCount: number
  winRate: number
  totalPnl: number
  todayPnl: number
  avgHoldMinutes: number
  lastSignalAt?: number
  lastTradeAt?: number
}

export interface AgentActivity {
  id: string
  timestamp: number
  type: 'SIGNAL' | 'TRADE' | 'ERROR' | 'STATUS' | 'INFO'
  message: string
  ticker?: string
  direction?: 'BUY' | 'SELL'
  pnl?: number
}

export interface Agent {
  id: string
  name: string
  displayName: string
  category: AgentCategory
  status: AgentStatus
  config: AgentConfig
  metrics: AgentMetrics
  recentActivity: AgentActivity[]
  startedAt?: number
  lastHeartbeat?: number
  version?: number
  tags?: string[]
}

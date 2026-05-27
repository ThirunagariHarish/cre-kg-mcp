/* ============================================================
   WebSocket Message Types
   ============================================================ */

export type WSMessageType =
  | 'QUOTE_UPDATE'
  | 'TICK'
  | 'SIGNAL_NEW'
  | 'SIGNAL_UPDATE'
  | 'ORDER_UPDATE'
  | 'POSITION_UPDATE'
  | 'PORTFOLIO_UPDATE'
  | 'RISK_UPDATE'
  | 'KILL_SWITCH'
  | 'AI_RECOMMENDATION'
  | 'AUDIT_EVENT'
  | 'SYSTEM_MESSAGE'
  | 'PING'
  | 'PONG'
  | 'SUBSCRIBE'
  | 'UNSUBSCRIBE'
  | 'ERROR'
  | 'CONNECTED'
  | 'RECONNECTING'

export interface WSMessage<T = unknown> {
  type: WSMessageType
  payload: T
  timestamp: number
  correlationId?: string
  sequenceNum?: number
}

export interface WSSubscribeMessage {
  type: 'SUBSCRIBE'
  channels: WSChannel[]
}

export interface WSUnsubscribeMessage {
  type: 'UNSUBSCRIBE'
  channels: WSChannel[]
}

export type WSChannel =
  | 'quotes'
  | 'signals'
  | 'orders'
  | 'portfolio'
  | 'risk'
  | 'audit'
  | 'system'
  | `quotes.${string}`  // quotes.AAPL

export interface WSQuoteUpdate {
  symbol: string
  last: number
  change: number
  changePercent: number
  bid: number
  ask: number
  volume: number
  timestamp: number
}

export interface WSOrderUpdate {
  orderId: string
  status: string
  filledQuantity?: number
  avgFillPrice?: number
  updatedAt: number
  errorMessage?: string
}

export interface WSSystemMessage {
  level: 'INFO' | 'WARNING' | 'ERROR' | 'SUCCESS'
  message: string
  source?: string
}

export type WSConnectionState =
  | 'CONNECTING'
  | 'CONNECTED'
  | 'RECONNECTING'
  | 'DISCONNECTED'
  | 'ERROR'

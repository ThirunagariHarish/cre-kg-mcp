/* ============================================================
   Audit & Event Types
   ============================================================ */

export type AuditLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'
export type AuditCategory =
  | 'ORDER'
  | 'SIGNAL'
  | 'RISK'
  | 'AI'
  | 'SYSTEM'
  | 'AUTH'
  | 'CONFIG'
  | 'MARKET_DATA'
  | 'PORTFOLIO'

export interface AuditEntry {
  id: string
  timestamp: number     // unix ms
  level: AuditLevel
  category: AuditCategory
  event: string         // e.g., "ORDER_SUBMITTED", "RISK_BREACH"
  message: string       // Human readable
  actor?: string        // user, system, AI
  entityId?: string     // orderId, signalId, etc.
  entityType?: string   // 'order', 'signal', 'position', etc.
  details?: Record<string, unknown>
  requestId?: string
  correlationId?: string
  duration?: number     // ms, for request/response events
}

export interface DomainEvent {
  id: string
  eventType: string     // e.g., "OrderFilled", "SignalReceived"
  aggregateId: string   // entity id
  aggregateType: string // e.g., "Order", "Signal"
  version: number
  payload: Record<string, unknown>
  metadata?: {
    correlationId?: string
    causationId?: string
    userId?: string
    timestamp: number
  }
  occurredAt: number
}

export interface AuditFilters {
  level?: AuditLevel[]
  category?: AuditCategory[]
  event?: string
  fromDate?: number
  toDate?: number
  entityId?: string
  search?: string
}

export interface SystemEvent {
  id: string
  type: 'INFO' | 'WARNING' | 'ERROR' | 'SUCCESS' | 'COMMAND'
  message: string
  timestamp: number
  source?: string
  raw?: string           // raw terminal output
  color?: 'cyan' | 'green' | 'red' | 'yellow' | 'white' | 'gray'
}

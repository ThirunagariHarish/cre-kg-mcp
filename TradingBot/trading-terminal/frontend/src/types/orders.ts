/* ============================================================
   Order Types
   ============================================================ */

export type OrderSide = 'BUY' | 'SELL'
export type OrderType = 'MARKET' | 'LIMIT' | 'STOP' | 'STOP_LIMIT' | 'TRAILING_STOP'
export type OrderStatus =
  | 'PENDING'
  | 'SUBMITTED'
  | 'PARTIALLY_FILLED'
  | 'FILLED'
  | 'CANCELLED'
  | 'REJECTED'
  | 'EXPIRED'
  | 'HELD'
export type OrderTIF = 'DAY' | 'GTC' | 'IOC' | 'FOK' | 'OPG' | 'CLS'
export type TradingMode = 'PAPER' | 'LIVE'

export interface Order {
  id: string
  clientOrderId?: string
  symbol: string
  side: OrderSide
  type: OrderType
  quantity: number
  filledQuantity: number
  limitPrice?: number
  stopPrice?: number
  trailingPercent?: number
  timeInForce: OrderTIF
  status: OrderStatus
  avgFillPrice?: number
  estimatedValue?: number
  filledValue?: number
  commission?: number
  submittedAt: number // unix ms
  updatedAt: number
  filledAt?: number
  cancelledAt?: number
  brokerOrderId?: string
  signalId?: string
  errorMessage?: string
  mode: TradingMode
  notes?: string
}

export interface OrderRequest {
  symbol: string
  side: OrderSide
  type: OrderType
  quantity: number
  limitPrice?: number
  stopPrice?: number
  timeInForce: OrderTIF
  signalId?: string
  notes?: string
}

export interface OrderUpdate {
  orderId: string
  status: OrderStatus
  filledQuantity?: number
  avgFillPrice?: number
  updatedAt: number
  errorMessage?: string
}

export interface OrderFilters {
  status?: OrderStatus[]
  side?: OrderSide[]
  symbol?: string
  fromDate?: number
  toDate?: number
  mode?: TradingMode
}

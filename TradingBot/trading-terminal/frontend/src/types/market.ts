/* ============================================================
   Market Data Types
   ============================================================ */

export interface Quote {
  symbol: string
  name?: string
  last: number
  previousClose: number
  open: number
  high: number
  low: number
  bid: number
  ask: number
  bidSize: number
  askSize: number
  volume: number
  avgVolume?: number
  change: number
  changePercent: number
  timestamp: number // unix ms
  exchange?: string
  currency?: string
  marketCap?: number
  pe?: number
  eps?: number
  week52High?: number
  week52Low?: number
}

export interface OHLCV {
  timestamp: number // unix ms
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface Tick {
  symbol: string
  price: number
  size: number
  timestamp: number
  side?: 'buy' | 'sell'
}

export interface WatchlistItem {
  symbol: string
  name?: string
  group?: string
  addedAt: number
  notes?: string
  alertPrice?: number
  alertDirection?: 'above' | 'below'
}

export interface WatchlistGroup {
  id: string
  name: string
  symbols: string[]
  color?: string
}

export interface MarketStatus {
  isOpen: boolean
  session: 'pre-market' | 'regular' | 'after-hours' | 'closed'
  nextOpen?: string
  nextClose?: string
  timezone: string
}

export interface Level2Quote {
  symbol: string
  bids: Array<{ price: number; size: number; exchange?: string }>
  asks: Array<{ price: number; size: number; exchange?: string }>
  timestamp: number
}

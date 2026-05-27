import { describe, it, expect, beforeEach } from 'vitest'
import { useMarketStore } from './marketStore'
import type { Quote } from '@/types/market'

// Minimal valid Quote factory
function makeQuote(symbol: string, last: number): Quote {
  return {
    symbol,
    last,
    previousClose: last - 1,
    open: last - 0.5,
    high: last + 1,
    low: last - 1,
    bid: last - 0.01,
    ask: last + 0.01,
    bidSize: 100,
    askSize: 100,
    volume: 1_000_000,
    change: 1,
    changePercent: 0.5,
    timestamp: Date.now(),
  }
}

// Merge only data fields — replace:true would wipe the action functions.
function resetStore() {
  useMarketStore.setState({
    watchlist: [],
    selectedSymbol: null,
    quotes: new Map(),
    previousQuotes: new Map(),
    isMarketOpen: false,
  })
}

describe('marketStore — addToWatchlist', () => {
  beforeEach(resetStore)

  it('adds a symbol to an empty watchlist', () => {
    useMarketStore.getState().addToWatchlist('AAPL')
    const { watchlist } = useMarketStore.getState()
    expect(watchlist).toHaveLength(1)
    expect(watchlist[0].symbol).toBe('AAPL')
  })

  it('sets the default group to "Watching"', () => {
    useMarketStore.getState().addToWatchlist('TSLA')
    expect(useMarketStore.getState().watchlist[0].group).toBe('Watching')
  })

  it('respects a custom group', () => {
    useMarketStore.getState().addToWatchlist('SPY', 'ETFs')
    expect(useMarketStore.getState().watchlist[0].group).toBe('ETFs')
  })

  it('ignores a duplicate symbol', () => {
    useMarketStore.getState().addToWatchlist('NVDA')
    useMarketStore.getState().addToWatchlist('NVDA')
    expect(useMarketStore.getState().watchlist).toHaveLength(1)
  })

  it('adds multiple distinct symbols', () => {
    useMarketStore.getState().addToWatchlist('AAPL')
    useMarketStore.getState().addToWatchlist('NVDA')
    useMarketStore.getState().addToWatchlist('MSFT')
    expect(useMarketStore.getState().watchlist).toHaveLength(3)
  })

  it('records addedAt as a recent unix ms timestamp', () => {
    const before = Date.now()
    useMarketStore.getState().addToWatchlist('AMD')
    const after = Date.now()
    const { addedAt } = useMarketStore.getState().watchlist[0]
    expect(addedAt).toBeGreaterThanOrEqual(before)
    expect(addedAt).toBeLessThanOrEqual(after)
  })
})

describe('marketStore — removeFromWatchlist', () => {
  beforeEach(resetStore)

  it('removes the matching symbol', () => {
    useMarketStore.getState().addToWatchlist('AAPL')
    useMarketStore.getState().addToWatchlist('NVDA')
    useMarketStore.getState().removeFromWatchlist('AAPL')
    const { watchlist } = useMarketStore.getState()
    expect(watchlist).toHaveLength(1)
    expect(watchlist[0].symbol).toBe('NVDA')
  })

  it('is a no-op when the symbol is not on the watchlist', () => {
    useMarketStore.getState().addToWatchlist('TSLA')
    useMarketStore.getState().removeFromWatchlist('XYZ')
    expect(useMarketStore.getState().watchlist).toHaveLength(1)
  })

  it('can empty the watchlist', () => {
    useMarketStore.getState().addToWatchlist('AAPL')
    useMarketStore.getState().removeFromWatchlist('AAPL')
    expect(useMarketStore.getState().watchlist).toHaveLength(0)
  })
})

describe('marketStore — updateQuote', () => {
  beforeEach(resetStore)

  it('stores the quote in the quotes map', () => {
    const q = makeQuote('AAPL', 180)
    useMarketStore.getState().updateQuote(q)
    expect(useMarketStore.getState().quotes.get('AAPL')).toEqual(q)
  })

  it('saves the previous quote before updating', () => {
    const first = makeQuote('AAPL', 180)
    const second = makeQuote('AAPL', 182)

    useMarketStore.getState().updateQuote(first)
    useMarketStore.getState().updateQuote(second)

    expect(useMarketStore.getState().quotes.get('AAPL')?.last).toBe(182)
    expect(useMarketStore.getState().previousQuotes.get('AAPL')?.last).toBe(180)
  })

  it('does not set previousQuote when no prior quote exists', () => {
    useMarketStore.getState().updateQuote(makeQuote('NVDA', 500))
    expect(useMarketStore.getState().previousQuotes.get('NVDA')).toBeUndefined()
  })

  it('handles multiple distinct symbols independently', () => {
    useMarketStore.getState().updateQuote(makeQuote('AAPL', 180))
    useMarketStore.getState().updateQuote(makeQuote('NVDA', 500))
    expect(useMarketStore.getState().quotes.size).toBe(2)
  })
})

describe('marketStore — setSelectedSymbol', () => {
  beforeEach(resetStore)

  it('sets a symbol', () => {
    useMarketStore.getState().setSelectedSymbol('TSLA')
    expect(useMarketStore.getState().selectedSymbol).toBe('TSLA')
  })

  it('updates to a different symbol', () => {
    useMarketStore.getState().setSelectedSymbol('AAPL')
    useMarketStore.getState().setSelectedSymbol('NVDA')
    expect(useMarketStore.getState().selectedSymbol).toBe('NVDA')
  })

  it('clears the selection with null', () => {
    useMarketStore.getState().setSelectedSymbol('AAPL')
    useMarketStore.getState().setSelectedSymbol(null)
    expect(useMarketStore.getState().selectedSymbol).toBeNull()
  })
})

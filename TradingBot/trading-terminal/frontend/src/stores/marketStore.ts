import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'
import type { Quote, WatchlistItem } from '@/types/market'

/** Persisted slice — written to localStorage under 'term-market-store'. */
interface PersistedMarketState {
  watchlist: WatchlistItem[]
  selectedSymbol: string | null
}

interface MarketState extends PersistedMarketState {
  // Watchlist
  addToWatchlist: (symbol: string, group?: string) => void
  removeFromWatchlist: (symbol: string) => void

  // Quotes cache (NOT persisted — Maps are not JSON-serialisable by default)
  quotes: Map<string, Quote>
  updateQuote: (quote: Quote) => void
  updateQuotes: (quotes: Quote[]) => void

  // Previous quotes (for flash animation)
  previousQuotes: Map<string, Quote>

  // Selected symbol
  setSelectedSymbol: (symbol: string | null) => void

  // Market status
  isMarketOpen: boolean
  setMarketOpen: (open: boolean) => void
}

const DEFAULT_WATCHLIST: WatchlistItem[] = [
  { symbol: 'AAPL', name: 'Apple Inc.', group: 'Watching', addedAt: Date.now() },
  { symbol: 'NVDA', name: 'NVIDIA Corp.', group: 'Watching', addedAt: Date.now() },
  { symbol: 'TSLA', name: 'Tesla Inc.', group: 'Watching', addedAt: Date.now() },
  { symbol: 'MSFT', name: 'Microsoft Corp.', group: 'Watching', addedAt: Date.now() },
  { symbol: 'AMD', name: 'Advanced Micro Devices', group: 'Watching', addedAt: Date.now() },
  { symbol: 'META', name: 'Meta Platforms', group: 'Watching', addedAt: Date.now() },
  { symbol: 'GOOGL', name: 'Alphabet Inc.', group: 'Watching', addedAt: Date.now() },
  { symbol: 'SPY', name: 'SPDR S&P 500 ETF', group: 'ETFs', addedAt: Date.now() },
  { symbol: 'QQQ', name: 'Invesco QQQ ETF', group: 'ETFs', addedAt: Date.now() },
]

export const useMarketStore = create<MarketState>()(
  devtools(
    persist(
      (set, _get) => ({
        // -------------------------------------------------------------- Persisted
        watchlist: DEFAULT_WATCHLIST,

        addToWatchlist: (symbol, group = 'Watching') =>
          set(state => {
            if (state.watchlist.some(i => i.symbol === symbol)) return state
            return {
              watchlist: [
                ...state.watchlist,
                { symbol, group, addedAt: Date.now() },
              ],
            }
          }),

        removeFromWatchlist: (symbol) =>
          set(state => ({
            watchlist: state.watchlist.filter(i => i.symbol !== symbol),
          })),

        selectedSymbol: null,
        setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),

        // ------------------------------------------------------------- Ephemeral
        quotes: new Map(),
        previousQuotes: new Map(),

        updateQuote: (quote) =>
          set(state => {
            const prev = state.quotes.get(quote.symbol)
            const newQuotes = new Map(state.quotes)
            newQuotes.set(quote.symbol, quote)

            const newPrev = new Map(state.previousQuotes)
            if (prev) newPrev.set(quote.symbol, prev)

            return { quotes: newQuotes, previousQuotes: newPrev }
          }),

        updateQuotes: (quotes) =>
          set(state => {
            const newQuotes = new Map(state.quotes)
            const newPrev = new Map(state.previousQuotes)

            quotes.forEach(q => {
              const prev = state.quotes.get(q.symbol)
              if (prev) newPrev.set(q.symbol, prev)
              newQuotes.set(q.symbol, q)
            })

            return { quotes: newQuotes, previousQuotes: newPrev }
          }),

        isMarketOpen: false,
        setMarketOpen: (open) => set({ isMarketOpen: open }),
      }),
      {
        name: 'term-market-store',
        // Persist only watchlist and selectedSymbol; Maps are not serialisable.
        partialize: (state): PersistedMarketState => ({
          watchlist: state.watchlist,
          selectedSymbol: state.selectedSymbol,
        }),
      }
    ),
    { name: 'market-store' }
  )
)

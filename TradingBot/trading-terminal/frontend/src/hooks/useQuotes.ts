import { useEffect, useState, useCallback } from 'react'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { useWebSocket } from './useWebSocket'
import type { Quote } from '@/types/market'

export function useQuotes(symbols: string[]) {
  const [quotes, setQuotes] = useState<Map<string, Quote>>(new Map())
  const [loading, setLoading] = useState(true)

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const symbolsKey = symbols.join(',')

  const fetchQuotes = useCallback(async () => {
    if (!symbols.length) {
      setLoading(false)
      return
    }
    try {
      const data = await apiGet<Record<string, Quote>>(API.quotes(symbolsKey))
      setQuotes(prev => {
        const next = new Map(prev)
        Object.entries(data).forEach(([sym, q]) => next.set(sym, q))
        return next
      })
    } catch {
      // silent fail — keep existing quotes
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolsKey])

  useEffect(() => {
    if (import.meta.env.VITE_MOCK_DATA === 'true') {
      setLoading(false)
      return
    }
    fetchQuotes()
    const id = setInterval(fetchQuotes, 5000)
    return () => clearInterval(id)
  }, [fetchQuotes])

  // Also update from WebSocket QUOTE_UPDATE events
  const { lastMessage } = useWebSocket()
  useEffect(() => {
    if (lastMessage?.type === 'QUOTE_UPDATE') {
      setQuotes(prev => {
        const next = new Map(prev)
        Object.entries(lastMessage.data as Record<string, Quote>).forEach(([sym, q]) =>
          next.set(sym, q),
        )
        return next
      })
    }
  }, [lastMessage])

  return { quotes, loading, refetch: fetchQuotes }
}

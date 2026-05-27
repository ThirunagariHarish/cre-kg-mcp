import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { useWebSocket } from './useWebSocket'
import type { Signal } from '@/types/signals'

interface SignalFeedResponse {
  signals?: Signal[]
  items?: Signal[]
  data?: Signal[]
}

/**
 * Queries GET /api/signals/feed?limit=20 and refreshes on SIGNAL_NEW
 * WebSocket events.
 */
export function useLiveSignals() {
  const qc = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['signal-feed'],
    queryFn: async (): Promise<Signal[]> => {
      const raw = await apiGet<Signal[] | SignalFeedResponse>(`${API.signalFeed}?limit=20`)
      if (Array.isArray(raw)) return raw
      return raw.signals ?? raw.items ?? raw.data ?? []
    },
    enabled: import.meta.env.VITE_MOCK_DATA !== 'true',
    refetchInterval: 5_000,
    placeholderData: [],
    retry: 1,
  })

  const { lastMessage } = useWebSocket()
  useEffect(() => {
    if (lastMessage?.type === 'SIGNAL_NEW') {
      qc.invalidateQueries({ queryKey: ['signal-feed'] })
    }
  }, [lastMessage, qc])

  return {
    signals: data ?? [],
    isLoading,
    error: error ?? null,
  }
}

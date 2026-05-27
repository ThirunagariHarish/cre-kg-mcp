import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { useWebSocket } from './useWebSocket'
import type { Order } from '@/types/orders'

interface OrdersResponse {
  orders?: Order[]
  items?: Order[]
  data?: Order[]
}

/**
 * Queries GET /api/orders and refreshes on ORDER_UPDATE WebSocket events.
 */
export function useLiveOrders() {
  const qc = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['orders'],
    queryFn: async (): Promise<Order[]> => {
      const raw = await apiGet<Order[] | OrdersResponse>(API.orders)
      if (Array.isArray(raw)) return raw
      return raw.orders ?? raw.items ?? raw.data ?? []
    },
    enabled: import.meta.env.VITE_MOCK_DATA !== 'true',
    refetchInterval: 5_000,
    placeholderData: [],
    retry: 1,
  })

  const { lastMessage } = useWebSocket()
  useEffect(() => {
    if (lastMessage?.type === 'ORDER_UPDATE') {
      qc.invalidateQueries({ queryKey: ['orders'] })
    }
  }, [lastMessage, qc])

  return {
    orders: data ?? [],
    isLoading,
    error: error ?? null,
  }
}

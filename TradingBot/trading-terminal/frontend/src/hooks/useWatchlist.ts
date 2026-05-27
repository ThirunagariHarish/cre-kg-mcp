import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiDelete } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import type { WatchlistItem } from '@/types/market'

export function useWatchlist() {
  const qc = useQueryClient()

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => apiGet<WatchlistItem[]>(API.watchlist),
    staleTime: 30_000,
    enabled: import.meta.env.VITE_MOCK_DATA !== 'true',
  })

  const addMutation = useMutation({
    mutationFn: (item: { symbol: string; name?: string; group?: string }) =>
      apiPost(API.watchlist, item),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })

  const removeMutation = useMutation({
    mutationFn: (symbol: string) => apiDelete(API.watchlistItem(symbol)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })

  return {
    items,
    isLoading,
    addSymbol: (symbol: string) => addMutation.mutate({ symbol }),
    removeSymbol: (symbol: string) => removeMutation.mutate(symbol),
  }
}

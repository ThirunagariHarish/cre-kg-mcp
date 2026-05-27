import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { QK } from '@/lib/queryKeys'

export interface IndexQuote {
  symbol: string
  last: number
  change: number
  changePercent: number
}

export function useIndices() {
  return useQuery({
    queryKey: QK.indices,
    queryFn: () => apiGet<Record<string, IndexQuote>>(API.marketIndices),
    refetchInterval: 5_000,
    placeholderData: {},
    retry: 1,
  })
}

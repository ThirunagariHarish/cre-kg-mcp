import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { QK } from '@/lib/queryKeys'

export interface ShortInterestData {
  symbol: string
  shortRatio?: number
  shortPercentOfFloat?: number
  sharesShort?: number
  sharesShortPriorMonth?: number
  floatShares?: number
  fetched_at: string
}

export function useShortInterest(symbol: string) {
  return useQuery({
    queryKey: QK.shortInterest(symbol),
    queryFn: () => apiGet<ShortInterestData>(API.shortInterest(symbol)),
    refetchInterval: 300_000, // 5 min
    enabled: !!symbol,
    retry: 1,
  })
}

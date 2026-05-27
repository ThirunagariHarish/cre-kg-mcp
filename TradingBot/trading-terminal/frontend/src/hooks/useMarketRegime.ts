import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { QK } from '@/lib/queryKeys'

export type MarketRegimeLabel =
  | 'BULL_QUIET'
  | 'BULL_VOLATILE'
  | 'BEAR_QUIET'
  | 'BEAR_VOLATILE'
  | 'NEUTRAL'

export interface MarketRegimeData {
  regime: MarketRegimeLabel
  confidence: number
}

interface RawRegimeResponse {
  regime?: string
  direction?: string
  confidence?: number
  trend?: string
  [key: string]: unknown
}

const VALID_REGIMES = new Set<MarketRegimeLabel>([
  'BULL_QUIET',
  'BULL_VOLATILE',
  'BEAR_QUIET',
  'BEAR_VOLATILE',
  'NEUTRAL',
])

function normaliseRegime(raw: string | undefined): MarketRegimeLabel {
  const up = (raw ?? '').toUpperCase()
  if (VALID_REGIMES.has(up as MarketRegimeLabel)) return up as MarketRegimeLabel

  // Map backend `market-direction` strings to regime labels.
  if (up.includes('BULL')) {
    return up.includes('VOLATILE') ? 'BULL_VOLATILE' : 'BULL_QUIET'
  }
  if (up.includes('BEAR')) {
    return up.includes('VOLATILE') ? 'BEAR_VOLATILE' : 'BEAR_QUIET'
  }
  return 'NEUTRAL'
}

const FALLBACK: MarketRegimeData = { regime: 'NEUTRAL', confidence: 0 }

/**
 * Polls `/api/market-direction` every 30 seconds.
 * Returns NEUTRAL with 0 confidence when the API is unavailable.
 */
export function useMarketRegime() {
  const { data, isLoading, error } = useQuery({
    queryKey: QK.marketRegime,
    queryFn: async (): Promise<MarketRegimeData> => {
      const raw = await apiGet<RawRegimeResponse>(API.marketRegime)
      return {
        regime: normaliseRegime(raw.regime ?? raw.direction ?? raw.trend),
        confidence: typeof raw.confidence === 'number' ? raw.confidence : 0,
      }
    },
    refetchInterval: 30_000,
    placeholderData: FALLBACK,
    retry: 1,
  })

  return {
    regime: data?.regime ?? FALLBACK.regime,
    confidence: data?.confidence ?? FALLBACK.confidence,
    isLoading,
    error: error ?? null,
  }
}

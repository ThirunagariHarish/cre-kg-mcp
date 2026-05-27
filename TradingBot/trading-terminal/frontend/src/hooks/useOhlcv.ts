import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { QK } from '@/lib/queryKeys'

export interface OhlcvBar {
  time: number    // unix seconds
  open: number
  high: number
  low: number
  close: number
  volume: number
}

interface OhlcvResponse {
  symbol: string
  bars: OhlcvBar[]
  count: number
}

const PERIOD_MAP: Record<string, string> = {
  '1m': '1d', '5m': '5d', '15m': '5d',
  '1h': '1mo', '4h': '3mo', '1D': '1y', '1W': '5y',
}
const INTERVAL_MAP: Record<string, string> = {
  '1m': '1m', '5m': '5m', '15m': '15m',
  '1h': '1h', '4h': '1h', '1D': '1d', '1W': '1wk',
}

export function useOhlcv(symbol: string, timeframe = '1h') {
  const period = PERIOD_MAP[timeframe] ?? '1mo'
  const interval = INTERVAL_MAP[timeframe] ?? '1h'
  return useQuery({
    queryKey: QK.ohlcv(symbol, period, interval),
    queryFn: async () => {
      const res = await apiGet<OhlcvResponse>(
        `${API.marketOhlcv(symbol)}?period=${period}&interval=${interval}`
      )
      // Normalize timestamps to unix seconds
      return res.bars.map(b => ({
        ...b,
        time:
          typeof b.time === 'string'
            ? Math.floor(new Date(b.time as unknown as string).getTime() / 1000)
            : b.time,
      }))
    },
    enabled: !!symbol,
    refetchInterval: 60_000,
    placeholderData: [],
    retry: 1,
  })
}

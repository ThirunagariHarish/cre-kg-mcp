import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { QK } from '@/lib/queryKeys'

export interface NewsItem {
  id: string
  ticker: string
  headline: string
  summary: string
  source: string
  url?: string
  timestamp: number  // unix seconds
  relatedTickers: string[]
  sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
}

export function useNews(
  symbols = 'SPY,QQQ,AAPL,NVDA,TSLA,AMD,META,GOOGL,AMZN,MSFT',
  limit = 20
) {
  return useQuery({
    queryKey: QK.news(symbols),
    queryFn: () =>
      apiGet<NewsItem[]>(
        `${API.marketNews}?symbols=${encodeURIComponent(symbols)}&limit=${limit}`
      ),
    refetchInterval: 60_000,
    placeholderData: [],
    retry: 1,
  })
}

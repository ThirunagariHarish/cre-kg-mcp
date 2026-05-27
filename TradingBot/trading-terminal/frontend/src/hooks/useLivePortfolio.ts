import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { useWebSocket } from './useWebSocket'
import type { Portfolio, Position } from '@/types/portfolio'

interface PortfolioSummaryResponse {
  cash?: number
  total_value?: number
  unrealized_pnl?: number
  day_pnl?: number
  positions?: Position[]
  position_count?: number
  // camelCase variants the backend may return
  cashBalance?: number
  totalValue?: number
  unrealizedPnl?: number
  dayPnl?: number
  positionCount?: number
}

const EMPTY_PORTFOLIO: Portfolio = {
  id: '',
  mode: 'PAPER',
  cashBalance: 0,
  equityValue: 0,
  totalValue: 0,
  dayPnl: 0,
  dayPnlPercent: 0,
  totalPnl: 0,
  totalPnlPercent: 0,
  positions: [],
  positionCount: 0,
  buyingPower: 0,
  timestamp: 0,
}

/**
 * Queries GET /api/portfolio/summary and refreshes on POSITION_UPDATE
 * WebSocket events.
 */
export function useLivePortfolio() {
  const qc = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['portfolio-summary'],
    queryFn: async () => {
      const raw = await apiGet<PortfolioSummaryResponse>(API.portfolioSummary)
      const positions = (raw.positions as Position[] | undefined) ?? []

      const summary: Portfolio = {
        id: '',
        mode: 'PAPER',
        cashBalance: raw.cash ?? raw.cashBalance ?? 0,
        equityValue: raw.total_value ?? raw.totalValue ?? 0,
        totalValue: raw.total_value ?? raw.totalValue ?? 0,
        dayPnl: raw.day_pnl ?? raw.dayPnl ?? 0,
        dayPnlPercent: 0,
        totalPnl: raw.unrealized_pnl ?? raw.unrealizedPnl ?? 0,
        totalPnlPercent: 0,
        positions,
        positionCount: raw.position_count ?? raw.positionCount ?? positions.length,
        buyingPower: raw.cash ?? raw.cashBalance ?? 0,
        timestamp: Date.now(),
      }
      return { summary, positions }
    },
    enabled: import.meta.env.VITE_MOCK_DATA !== 'true',
    refetchInterval: 5_000,
    placeholderData: { summary: EMPTY_PORTFOLIO, positions: [] },
    retry: 1,
  })

  const { lastMessage } = useWebSocket()
  useEffect(() => {
    if (lastMessage?.type === 'POSITION_UPDATE') {
      qc.invalidateQueries({ queryKey: ['portfolio-summary'] })
    }
  }, [lastMessage, qc])

  return {
    summary: data?.summary ?? EMPTY_PORTFOLIO,
    positions: data?.positions ?? [],
    isLoading,
    error: error ?? null,
  }
}

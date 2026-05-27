import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { apiGet, apiPost, apiDelete } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { useWebSocket } from './useWebSocket'
import type { RiskStatus } from '@/types/risk'

export function useRiskStatus() {
  const qc = useQueryClient()

  const { data: riskStatus, isLoading } = useQuery({
    queryKey: ['risk-status'],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    queryFn: () => apiGet<any>(API.riskStatus),
    refetchInterval: 10_000,
    enabled: import.meta.env.VITE_MOCK_DATA !== 'true',
  })

  const { lastMessage } = useWebSocket()
  useEffect(() => {
    if (lastMessage?.type === 'RISK_BREACH') {
      qc.invalidateQueries({ queryKey: ['risk-status'] })
    }
  }, [lastMessage, qc])

  const activateStop = useMutation({
    mutationFn: (reason: string) => apiPost(API.emergencyStopActivate, { reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['risk-status'] }),
  })

  const deactivateStop = useMutation({
    mutationFn: () => apiDelete<RiskStatus>(API.emergencyStopDeactivate),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['risk-status'] }),
  })

  return {
    riskStatus: riskStatus as RiskStatus | undefined,
    isLoading,
    activateEmergencyStop: (reason: string) => activateStop.mutate(reason),
    deactivateEmergencyStop: () => deactivateStop.mutate(),
    isHalted: (riskStatus as RiskStatus | undefined)?.killSwitchActive ?? false,
  }
}

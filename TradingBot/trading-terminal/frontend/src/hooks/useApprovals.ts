import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { QK } from '@/lib/queryKeys'
import { useTerminalStore } from '@/stores/terminalStore'

export interface Approval {
  id: string
  signalId?: string
  symbol?: string
  direction?: string
  confidence?: number
  requestedAt: number
  status: 'PENDING' | 'APPROVED' | 'REJECTED'
  notes?: string
  [key: string]: unknown
}

interface ApprovalsResponse {
  approvals?: Approval[]
  items?: Approval[]
  data?: Approval[]
}

/**
 * Polls `/api/approvals` every 3 seconds.
 */
export function useApprovals() {
  const { data, isLoading, error } = useQuery({
    queryKey: QK.approvals,
    queryFn: async (): Promise<Approval[]> => {
      const raw = await apiGet<Approval[] | ApprovalsResponse>(API.approvals)
      if (Array.isArray(raw)) return raw
      return raw.approvals ?? raw.items ?? raw.data ?? []
    },
    refetchInterval: 3_000,
    placeholderData: [],
    retry: 1,
  })

  return {
    approvals: data ?? [],
    isLoading,
    error: error ?? null,
  }
}

/**
 * Mutation to approve a pending signal by id.
 * Invalidates the approvals query on success.
 */
export function useApproveMutation(id: string) {
  const queryClient = useQueryClient()
  const addAlert = useTerminalStore(s => s.addAlert)
  const addConsoleEvent = useTerminalStore(s => s.addConsoleEvent)

  return useMutation({
    mutationFn: () => apiPost<unknown>(API.approveSignal(id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QK.approvals })
      addAlert({ type: 'FILL_COMPLETE', message: `Approval ${id} approved` })
      addConsoleEvent({
        id: crypto.randomUUID(),
        type: 'SUCCESS',
        message: `Approval ${id} approved`,
        timestamp: Date.now(),
        source: 'APPROVALS',
      })
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : 'Approve failed'
      addAlert({ type: 'ERROR', message: `Approve ${id} failed: ${message}` })
      addConsoleEvent({
        id: crypto.randomUUID(),
        type: 'ERROR',
        message: `Approve ${id} failed: ${message}`,
        timestamp: Date.now(),
        source: 'APPROVALS',
        color: 'red',
      })
    },
  })
}

/**
 * Mutation to reject a pending signal by id.
 * Invalidates the approvals query on success.
 */
export function useRejectMutation(id: string) {
  const queryClient = useQueryClient()
  const addAlert = useTerminalStore(s => s.addAlert)
  const addConsoleEvent = useTerminalStore(s => s.addConsoleEvent)

  return useMutation({
    mutationFn: () => apiPost<unknown>(API.rejectSignal(id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QK.approvals })
      addAlert({ type: 'INFO', message: `Approval ${id} rejected` })
      addConsoleEvent({
        id: crypto.randomUUID(),
        type: 'INFO',
        message: `Approval ${id} rejected`,
        timestamp: Date.now(),
        source: 'APPROVALS',
      })
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : 'Reject failed'
      addAlert({ type: 'ERROR', message: `Reject ${id} failed: ${message}` })
      addConsoleEvent({
        id: crypto.randomUUID(),
        type: 'ERROR',
        message: `Reject ${id} failed: ${message}`,
        timestamp: Date.now(),
        source: 'APPROVALS',
        color: 'red',
      })
    },
  })
}

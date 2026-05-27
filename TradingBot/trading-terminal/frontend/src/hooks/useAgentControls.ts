import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiPost } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { QK } from '@/lib/queryKeys'
import { useTerminalStore } from '@/stores/terminalStore'

/**
 * React Query mutations for controlling a single agent (start / stop / restart).
 *
 * Each mutation:
 *  - Calls the corresponding POST endpoint.
 *  - On success: invalidates fleet and agent query caches, adds a console event
 *    and an INFO alert.
 *  - On error: adds a console event and an ERROR alert.
 */
export function useAgentControls(agentName: string) {
  const queryClient = useQueryClient()
  const addConsoleEvent = useTerminalStore(s => s.addConsoleEvent)
  const addAlert = useTerminalStore(s => s.addAlert)

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: QK.fleet })
    void queryClient.invalidateQueries({ queryKey: QK.agent(agentName) })
  }

  function onSuccess(action: string) {
    invalidate()
    addConsoleEvent({
      id: crypto.randomUUID(),
      type: 'SUCCESS',
      message: `Agent ${agentName}: ${action} succeeded`,
      timestamp: Date.now(),
      source: 'AGENT',
    })
    addAlert({
      type: 'FILL_COMPLETE',
      message: `Agent ${agentName} ${action}`,
      symbol: agentName,
    })
  }

  function onError(action: string, err: unknown) {
    const message =
      err instanceof Error ? err.message : `${action} failed`
    addConsoleEvent({
      id: crypto.randomUUID(),
      type: 'ERROR',
      message: `Agent ${agentName}: ${action} error — ${message}`,
      timestamp: Date.now(),
      source: 'AGENT',
      color: 'red',
    })
    addAlert({
      type: 'ERROR',
      message: `Agent ${agentName} ${action} failed: ${message}`,
      symbol: agentName,
    })
  }

  const start = useMutation({
    mutationFn: () => apiPost<unknown>(API.agentStart(agentName)),
    onSuccess: () => onSuccess('started'),
    onError: (err) => onError('start', err),
  })

  const stop = useMutation({
    mutationFn: () => apiPost<unknown>(API.agentStop(agentName)),
    onSuccess: () => onSuccess('stopped'),
    onError: (err) => onError('stop', err),
  })

  const restart = useMutation({
    mutationFn: () => apiPost<unknown>(API.agentRestart(agentName)),
    onSuccess: () => onSuccess('restarted'),
    onError: (err) => onError('restart', err),
  })

  return { start, stop, restart }
}

import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { QK } from '@/lib/queryKeys'
import type { Agent, AgentStatus, AgentCategory } from '@/types/agents'

/** Shape the backend returns for a single fleet entry. */
interface RawAgent {
  name?: string
  display_name?: string
  displayName?: string
  status?: string
  category?: string
  config?: Agent['config']
  metrics?: Agent['metrics']
  started_at?: number
  startedAt?: number
  last_heartbeat?: number
  lastHeartbeat?: number
  version?: number
  tags?: string[]
}

interface FleetResponse {
  agents?: RawAgent[]
  [key: string]: unknown
}

const VALID_STATUSES = new Set<AgentStatus>([
  'RUNNING', 'PAUSED', 'STOPPED', 'ERROR', 'IDLE',
])

const VALID_CATEGORIES = new Set<AgentCategory>([
  'ALGORITHM', 'DISCORD', 'AI', 'DATA', 'PORTFOLIO', 'OPTIONS',
])

function coerceStatus(raw: string | undefined): AgentStatus {
  const up = (raw ?? '').toUpperCase() as AgentStatus
  return VALID_STATUSES.has(up) ? up : 'IDLE'
}

function coerceCategory(raw: string | undefined): AgentCategory {
  const up = (raw ?? '').toUpperCase() as AgentCategory
  return VALID_CATEGORIES.has(up) ? up : 'ALGORITHM'
}

function toAgent(raw: RawAgent): Agent {
  const name = raw.name ?? 'unknown'
  return {
    id: name,
    name,
    displayName: raw.displayName ?? raw.display_name ?? name,
    category: coerceCategory(raw.category),
    status: coerceStatus(raw.status),
    config: raw.config ?? { name },
    metrics: raw.metrics ?? {
      totalSignals: 0,
      executedTrades: 0,
      winCount: 0,
      lossCount: 0,
      winRate: 0,
      totalPnl: 0,
      todayPnl: 0,
      avgHoldMinutes: 0,
    },
    recentActivity: [],
    startedAt: raw.startedAt ?? raw.started_at,
    lastHeartbeat: raw.lastHeartbeat ?? raw.last_heartbeat,
    version: raw.version,
    tags: raw.tags,
  }
}

/**
 * Polls `/api/fleet` every 3 seconds and maps the raw response to Agent[].
 * Returns an empty array if the API is unavailable.
 */
export function useLiveFleet() {
  const { data, isLoading, error } = useQuery({
    queryKey: QK.fleet,
    queryFn: async (): Promise<Agent[]> => {
      const raw = await apiGet<FleetResponse | RawAgent[]>(API.fleet)
      const list = Array.isArray(raw) ? raw : (raw.agents ?? [])
      return list.map(toAgent)
    },
    refetchInterval: 3_000,
    placeholderData: [],
    retry: 1,
  })

  return {
    agents: data ?? [],
    isLoading,
    error: error ?? null,
  }
}

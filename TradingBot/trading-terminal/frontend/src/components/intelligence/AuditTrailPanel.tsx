import React, { useState, useMemo } from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ────────────────────────────────────────────────────────────────────

type AuditEventType = 'TRADE' | 'SIGNAL' | 'AGENT' | 'RISK' | 'SYSTEM' | 'AUTH'

export interface AuditEvent {
  id: string
  timestamp: Date
  type: AuditEventType
  source: string
  description: string
  metadata?: string
}

/**
 * Props for AuditTrailPanel.
 * @prop events  - Audit events to display.
 * @prop loading - Show skeleton loading state.
 */
export interface AuditTrailPanelProps {
  events?: AuditEvent[]
  loading?: boolean
}

// ── API response shape ────────────────────────────────────────────────────────

interface AuditEventRaw {
  id: string
  timestamp: string | number
  event_type?: string
  type?: string
  source?: string
  description?: string
  message?: string
  metadata?: string | null
}

// ── Event type styles ─────────────────────────────────────────────────────────

const TYPE_STYLE: Record<AuditEventType, { label: string; cls: string }> = {
  TRADE:  { label: 'TRADE',  cls: 'text-positive border-positive-dim bg-positive-bg' },
  SIGNAL: { label: 'SIGNAL', cls: 'text-accent-cyan border-[rgba(255,102,0,0.3)] bg-[rgba(255,102,0,0.1)]' },
  AGENT:  { label: 'AGENT',  cls: 'text-accent-purple border-[rgba(171,71,188,0.3)] bg-[rgba(171,71,188,0.1)]' },
  RISK:   { label: 'RISK',   cls: 'text-negative border-negative-dim bg-negative-bg' },
  SYSTEM: { label: 'SYS',    cls: 'text-text-secondary border-border-subtle bg-bg-panel-raised' },
  AUTH:   { label: 'AUTH',   cls: 'text-warning border-warning-dim bg-warning-bg' },
}

const PAGE_SIZE = 50

// ── Main component ────────────────────────────────────────────────────────────

export default function AuditTrailPanel({
  events: eventsProp,
  loading: loadingProp = false,
}: AuditTrailPanelProps) {
  const { data: rawEvents, isLoading: apiLoading } = useQuery({
    queryKey: ['audit-log'],
    queryFn: async () => {
      const raw = await apiGet<AuditEventRaw[] | { items?: AuditEventRaw[]; data?: AuditEventRaw[] }>(API.auditLog)
      const items: AuditEventRaw[] = Array.isArray(raw) ? raw : (raw.items ?? raw.data ?? [])
      return items.map((e): AuditEvent => ({
        id: e.id,
        timestamp: new Date(typeof e.timestamp === 'number' ? e.timestamp : Date.parse(e.timestamp)),
        type: ((e.event_type ?? e.type ?? 'SYSTEM') as AuditEventType),
        source: e.source ?? 'System',
        description: e.description ?? e.message ?? '',
        metadata: e.metadata ?? undefined,
      }))
    },
    enabled: import.meta.env.VITE_MOCK_DATA !== 'true' && !eventsProp,
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: 1,
  })

  const loading = loadingProp || apiLoading
  const events: AuditEvent[] = eventsProp ?? rawEvents ?? []
  const [activeTypes, setActiveTypes] = useState<Set<AuditEventType>>(new Set())
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)

  const toggleType = (type: AuditEventType) => {
    setActiveTypes(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
    setPage(0)
  }

  const filtered = useMemo(() => {
    return events.filter(e => {
      if (activeTypes.size > 0 && !activeTypes.has(e.type)) return false
      if (search) {
        const q = search.toLowerCase()
        if (
          !e.description.toLowerCase().includes(q) &&
          !e.source.toLowerCase().includes(q) &&
          !(e.metadata?.toLowerCase().includes(q) ?? false)
        ) return false
      }
      return true
    })
  }, [events, activeTypes, search])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header"><span>◈ Audit Trail</span></div>
        <div className="p-2 space-y-1">
          {Array.from({ length: 8 }).map((_, i) => <div key={i} className="h-6 skeleton rounded-sm" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Audit Trail</span>
        <span className="font-mono text-[0.52rem] text-text-muted tabular-nums">{filtered.length} events</span>
      </div>

      {/* Type filter toggles */}
      <div className="flex items-center gap-1 px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0 flex-wrap">
        {(Object.keys(TYPE_STYLE) as AuditEventType[]).map(type => {
          const active = activeTypes.has(type)
          return (
            <button
              key={type}
              onClick={() => toggleType(type)}
              className={clsx(
                'font-mono text-[0.55rem] px-1.5 py-0.5 rounded-sm border transition-colors',
                active
                  ? TYPE_STYLE[type].cls
                  : 'text-text-muted border-border-muted hover:border-border-subtle',
              )}
            >
              {TYPE_STYLE[type].label}
            </button>
          )
        })}
        {activeTypes.size > 0 && (
          <button
            onClick={() => setActiveTypes(new Set())}
            className="font-mono text-[0.52rem] text-accent-cyan hover:underline ml-1"
          >
            clear
          </button>
        )}
      </div>

      {/* Search */}
      <div className="px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0">
        <input
          className="terminal-input text-[0.65rem]"
          placeholder="Search ticker, agent, event..."
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(0) }}
        />
      </div>

      {/* Event log */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {paginated.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <span className="font-mono text-[0.65rem] text-text-muted">No events matching filter</span>
          </div>
        ) : (
          paginated.map(event => {
            const ts = TYPE_STYLE[event.type]
            const ago = formatDistanceToNow(event.timestamp, { addSuffix: true })
            return (
              <div
                key={event.id}
                className="flex items-start gap-2 px-2.5 py-1.5 border-b border-border-muted hover:bg-bg-panel-hover transition-colors"
              >
                {/* Timestamp */}
                <span className="font-mono text-[0.55rem] text-text-muted flex-shrink-0 tabular-nums w-[70px]">
                  {event.timestamp.toTimeString().slice(0, 8)}
                </span>

                {/* Type badge */}
                <span className={clsx('font-mono text-[0.48rem] px-1 py-px border rounded-sm flex-shrink-0 w-10 text-center', ts.cls)}>
                  {ts.label}
                </span>

                {/* Source */}
                <span className="font-mono text-[0.55rem] text-text-muted flex-shrink-0 w-[90px] truncate">
                  {event.source}
                </span>

                {/* Description */}
                <span className="font-mono text-[0.62rem] text-text-secondary flex-1 min-w-0 leading-relaxed">
                  {event.description}
                </span>

                {/* Metadata */}
                <div className="flex-shrink-0 text-right">
                  {event.metadata && (
                    <span className="font-mono text-[0.5rem] text-text-muted block truncate max-w-[80px]" title={event.metadata}>
                      {event.metadata}
                    </span>
                  )}
                  <span className="font-mono text-[0.48rem] text-text-muted block">{ago}</span>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-2.5 py-1.5 border-t border-border-subtle flex-shrink-0 bg-bg-panel">
          <button
            disabled={page === 0}
            onClick={() => setPage(p => p - 1)}
            className="font-mono text-[0.58rem] text-text-muted disabled:opacity-30 hover:text-accent-cyan transition-colors"
          >
            ‹ Prev
          </button>
          <span className="font-mono text-[0.55rem] text-text-muted tabular-nums">
            {page + 1} / {totalPages}
          </span>
          <button
            disabled={page >= totalPages - 1}
            onClick={() => setPage(p => p + 1)}
            className="font-mono text-[0.58rem] text-text-muted disabled:opacity-30 hover:text-accent-cyan transition-colors"
          >
            Next ›
          </button>
        </div>
      )}
    </div>
  )
}

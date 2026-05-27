import React, { useState, useMemo } from 'react'
import clsx from 'clsx'
import { format, formatDistanceToNow, isAfter, isBefore, parseISO } from 'date-fns'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

/* ─────────────────────────────────────────────
   Types
───────────────────────────────────────────── */

export type TimelineEventType = 'SIGNAL' | 'TRADE' | 'SCAN' | 'ERROR' | 'STATUS' | 'CONFIG'

export interface AgentTimelineEvent {
  id: string
  timestamp: number
  type: TimelineEventType
  title: string
  details?: Record<string, string | number | boolean>
  /** Optional: ticker symbol for SIGNAL/TRADE */
  ticker?: string
  /** Optional: P&L for TRADE events */
  pnl?: number
}

interface AgentTimelinePanelProps {
  agentName: string
  events?: AgentTimelineEvent[]
  loading?: boolean
}


/* ─────────────────────────────────────────────
   Event config
───────────────────────────────────────────── */

const EVENT_CONFIG: Record<TimelineEventType, {
  icon: string
  dotColor: string
  lineColor: string
  textColor: string
  bgColor: string
}> = {
  SIGNAL: { icon: '◎', dotColor: 'bg-accent-cyan',    lineColor: 'bg-accent-cyan',   textColor: 'text-accent-cyan',   bgColor: 'bg-bg-panel-raised' },
  TRADE:  { icon: '⬟', dotColor: 'bg-info',           lineColor: 'bg-info',          textColor: 'text-info',          bgColor: 'bg-info-bg' },
  SCAN:   { icon: '⟳', dotColor: 'bg-warning',        lineColor: 'bg-warning',       textColor: 'text-warning',       bgColor: 'bg-bg-panel-raised' },
  ERROR:  { icon: '✕', dotColor: 'bg-negative',       lineColor: 'bg-negative',      textColor: 'text-negative',      bgColor: 'bg-negative-bg' },
  STATUS: { icon: '◉', dotColor: 'bg-text-secondary', lineColor: 'bg-border-subtle', textColor: 'text-text-secondary', bgColor: 'bg-bg-panel-raised' },
  CONFIG: { icon: '⚙', dotColor: 'bg-accent-purple',  lineColor: 'bg-accent-purple', textColor: 'text-accent-purple', bgColor: 'bg-bg-panel-raised' },
}

/* ─────────────────────────────────────────────
   Timeline event row
───────────────────────────────────────────── */

function TimelineEventRow({ event, isLast }: { event: AgentTimelineEvent; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = EVENT_CONFIG[event.type]
  const hasDetails = event.details && Object.keys(event.details).length > 0

  return (
    <div className="flex gap-3 relative">
      {/* Connector line */}
      {!isLast && (
        <div
          className={clsx('absolute left-[7px] top-[18px] w-px', cfg.lineColor)}
          style={{ bottom: 0, opacity: 0.3 }}
        />
      )}

      {/* Dot */}
      <div className="flex-shrink-0 flex flex-col items-center mt-1">
        <div className={clsx('w-3.5 h-3.5 rounded-full flex items-center justify-center z-10', cfg.dotColor)}>
          <span className="text-[0.4rem] text-black leading-none">{cfg.icon}</span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 pb-3 min-w-0">
        <div
          className={clsx(
            'flex items-start gap-2 cursor-pointer group',
            hasDetails && 'hover:opacity-90'
          )}
          onClick={() => hasDetails && setExpanded(v => !v)}
          role={hasDetails ? 'button' : undefined}
          aria-expanded={hasDetails ? expanded : undefined}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className={clsx(
                'font-mono text-[0.52rem] px-1 py-px border rounded-sm flex-shrink-0',
                cfg.textColor,
                cfg.dotColor.replace('bg-', 'border-')
              )}>
                {event.type}
              </span>
              {event.ticker && (
                <span className="font-mono text-[0.58rem] text-accent-cyan">[{event.ticker}]</span>
              )}
              {event.pnl !== undefined && (
                <span className={clsx('font-mono text-[0.58rem] font-semibold tabular-nums', event.pnl >= 0 ? 'text-positive' : 'text-negative')}>
                  {event.pnl >= 0 ? '+' : ''}{event.pnl}
                </span>
              )}
            </div>
            <p className={clsx('font-mono text-[0.65rem] mt-0.5 leading-snug', cfg.textColor)}>
              {event.title}
            </p>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            <span className="font-mono text-[0.52rem] text-text-muted whitespace-nowrap">
              {formatDistanceToNow(event.timestamp, { addSuffix: true })}
            </span>
            {hasDetails && (
              expanded
                ? <ChevronDown size={9} className="text-text-muted" />
                : <ChevronRight size={9} className="text-text-muted" />
            )}
          </div>
        </div>

        {/* Timestamp */}
        <p className="font-mono text-[0.5rem] text-text-muted mt-0.5">
          {format(event.timestamp, 'yyyy-MM-dd HH:mm:ss')}
        </p>

        {/* Expanded details */}
        {expanded && event.details && (
          <div className={clsx('mt-1.5 rounded-sm border border-border-subtle p-2', cfg.bgColor)}>
            <table className="w-full">
              <tbody>
                {Object.entries(event.details).map(([k, v]) => (
                  <tr key={k}>
                    <td className="font-mono text-[0.55rem] text-text-muted pr-3 pb-0.5 w-1/2">{k}</td>
                    <td className="font-mono text-[0.58rem] text-text-primary pb-0.5 tabular-nums">
                      {String(v)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Main component
───────────────────────────────────────────── */

const ALL_TYPES: TimelineEventType[] = ['SIGNAL', 'TRADE', 'SCAN', 'ERROR', 'STATUS', 'CONFIG']

export default function AgentTimelinePanel({
  agentName,
  events,
  loading = false,
}: AgentTimelinePanelProps) {
  const [enabledTypes, setEnabledTypes] = useState<Set<TimelineEventType>>(new Set(ALL_TYPES))
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const { data: fetchedEvents = [] } = useQuery({
    queryKey: ['agent-timeline', agentName],
    queryFn: () => apiGet<any[]>(API.agentTimeline(agentName)),
    refetchInterval: 10_000,
    enabled: !!agentName && !events,
    placeholderData: [],
  })

  const displayEvents: AgentTimelineEvent[] = (events ?? fetchedEvents).map((e: any) => ({
    id: e.id ?? `${agentName}-${e.timestamp ?? Date.now()}`,
    timestamp: typeof e.timestamp === 'string'
      ? new Date(e.timestamp).getTime()
      : (e.timestamp ?? Date.now()),
    type: (['SIGNAL','TRADE','SCAN','ERROR','STATUS','CONFIG'].includes(e.type?.toUpperCase())
      ? e.type.toUpperCase()
      : (e.event ? e.event.toUpperCase() : 'STATUS')) as AgentTimelineEvent['type'],
    title: e.title ?? e.message ?? e.event ?? 'Event',
    details: e.details,
    ticker: e.ticker,
    pnl: e.pnl,
  }))

  const toggleType = (t: TimelineEventType) => {
    setEnabledTypes(prev => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })
  }

  const filtered = useMemo(() => {
    return displayEvents.filter(e => {
      if (!enabledTypes.has(e.type)) return false
      if (dateFrom) {
        try { if (isBefore(e.timestamp, parseISO(dateFrom))) return false } catch { /* ignore */ }
      }
      if (dateTo) {
        try { if (isAfter(e.timestamp, parseISO(dateTo))) return false } catch { /* ignore */ }
      }
      return true
    })
  }, [displayEvents, enabledTypes, dateFrom, dateTo])

  return (
    <div className="flex flex-col h-full overflow-hidden bg-bg-panel">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1 truncate">◈ Agent Timeline — {agentName}</span>
        <span className="font-mono text-[0.52rem] text-text-muted">{filtered.length} events</span>
      </div>

      {/* Filters */}
      <div className="px-3 py-2 border-b border-border-subtle flex-shrink-0 space-y-2">
        {/* Type checkboxes */}
        <div className="flex items-center gap-2 flex-wrap">
          {ALL_TYPES.map(t => {
            const cfg = EVENT_CONFIG[t]
            const active = enabledTypes.has(t)
            return (
              <button
                key={t}
                onClick={() => toggleType(t)}
                className={clsx(
                  'flex items-center gap-1 px-1.5 py-0.5 font-mono text-[0.52rem] border rounded-sm transition-colors',
                  active
                    ? clsx(cfg.textColor, cfg.dotColor.replace('bg-', 'border-'))
                    : 'text-text-muted border-border-subtle opacity-40 hover:opacity-70'
                )}
                aria-pressed={active}
              >
                <span className={clsx('w-1.5 h-1.5 rounded-full', active ? cfg.dotColor : 'bg-text-muted')} />
                {t}
              </button>
            )
          })}
        </div>
        {/* Date range */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-[0.52rem] text-text-muted">FROM</span>
          <input
            type="date"
            value={dateFrom}
            onChange={e => setDateFrom(e.target.value)}
            className="terminal-input w-auto text-[0.6rem] py-0.5"
            aria-label="Filter from date"
          />
          <span className="font-mono text-[0.52rem] text-text-muted">TO</span>
          <input
            type="date"
            value={dateTo}
            onChange={e => setDateTo(e.target.value)}
            className="terminal-input w-auto text-[0.6rem] py-0.5"
            aria-label="Filter to date"
          />
          {(dateFrom || dateTo) && (
            <button
              onClick={() => { setDateFrom(''); setDateTo('') }}
              className="font-mono text-[0.55rem] text-text-muted hover:text-text-secondary"
            >
              CLEAR
            </button>
          )}
        </div>
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-y-auto min-h-0 px-3 py-3">
        {loading ? (
          <div className="flex items-center justify-center h-20 text-text-muted font-mono text-[0.62rem]">
            Loading timeline...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex items-center justify-center h-20 text-text-muted font-mono text-[0.62rem]">
            No events match filter
          </div>
        ) : (
          <div>
            {filtered.map((event, index) => (
              <TimelineEventRow
                key={event.id}
                event={event}
                isLast={index === filtered.length - 1}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

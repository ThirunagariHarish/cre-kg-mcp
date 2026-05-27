import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import clsx from 'clsx'
import { Download, Trash2, Search, ChevronDown, ChevronUp } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

/* ─────────────────────────────────────────────
   Types
───────────────────────────────────────────── */

export type LogLevel = 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG' | 'TRADE'

export interface AgentLogEntry {
  id: string
  timestamp: number
  level: LogLevel
  message: string
  data?: Record<string, unknown>
}

interface AgentLogViewerProps {
  /** Agent name shown in header */
  agentName: string
  /** Current status badge */
  agentStatus?: 'RUNNING' | 'PAUSED' | 'STOPPED' | 'ERROR' | 'IDLE'
  /** Log entries to display */
  logs?: AgentLogEntry[]
  /** Called when user clicks the X close button */
  onClose?: () => void
}


/* ─────────────────────────────────────────────
   Level config
───────────────────────────────────────────── */

const LEVEL_CONFIG: Record<LogLevel, { color: string; bg: string; label: string }> = {
  INFO:    { color: 'text-info',          bg: 'bg-info-bg',          label: 'INFO ' },
  WARNING: { color: 'text-warning',       bg: 'bg-warning-bg',       label: 'WARN ' },
  ERROR:   { color: 'text-negative',      bg: 'bg-negative-bg',      label: 'ERROR' },
  DEBUG:   { color: 'text-text-muted',    bg: 'bg-bg-panel-raised',  label: 'DEBUG' },
  TRADE:   { color: 'text-positive',      bg: 'bg-positive-bg',      label: 'TRADE' },
}

const STATUS_DOT: Record<string, string> = {
  RUNNING: 'bg-positive animate-pulse',
  PAUSED:  'bg-warning',
  STOPPED: 'bg-text-muted',
  ERROR:   'bg-negative animate-pulse',
  IDLE:    'bg-accent-amber',
}

type LevelFilter = LogLevel | 'ALL'
const LEVEL_FILTERS: LevelFilter[] = ['ALL', 'INFO', 'WARN', 'ERROR', 'TRADE']

function formatTs(ts: number): string {
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `${hh}:${mm}:${ss}.${ms}`
}

/* ─────────────────────────────────────────────
   Component
───────────────────────────────────────────── */

export default function AgentLogViewer({
  agentName,
  agentStatus = 'RUNNING',
  logs,
  onClose,
}: AgentLogViewerProps) {
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('ALL')
  const [search, setSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  const { data: fetchedLogs = [] } = useQuery({
    queryKey: ['agent-logs', agentName],
    queryFn: () => apiGet<any[]>(API.agentLogs(agentName)),
    refetchInterval: 5_000,
    enabled: !!agentName && !logs,
    placeholderData: [],
  })

  const displayLogs: AgentLogEntry[] = (logs ?? fetchedLogs).map((l: any) => ({
    id: l.id ?? `${agentName}-${l.timestamp ?? Date.now()}`,
    timestamp: typeof l.timestamp === 'string'
      ? new Date(l.timestamp).getTime()
      : (l.timestamp ?? Date.now()),
    level: (['INFO','WARNING','ERROR','DEBUG','TRADE'].includes(l.level?.toUpperCase())
      ? l.level.toUpperCase()
      : 'INFO') as AgentLogEntry['level'],
    message: l.message ?? '',
    data: l.data,
  }))

  // Normalize filter: 'WARN' maps to 'WARNING'
  const normalizeFilter = (f: LevelFilter): LogLevel | 'ALL' =>
    f === 'WARN' ? 'WARNING' : (f as LogLevel | 'ALL')

  const filtered = useMemo(() => {
    const norm = normalizeFilter(levelFilter)
    return displayLogs.filter(entry => {
      if (norm !== 'ALL' && entry.level !== norm) return false
      if (search && !entry.message.toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }, [displayLogs, levelFilter, search])

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [filtered, autoScroll])

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 20
    if (!atBottom && autoScroll) setAutoScroll(false)
  }, [autoScroll])

  const handleExport = useCallback(() => {
    const lines = filtered.map(
      e => `${formatTs(e.timestamp)} [${e.level.padEnd(7)}] ${e.message}`
    ).join('\n')
    const blob = new Blob([lines], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${agentName}_logs_${Date.now()}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }, [filtered, agentName])

  const dotClass = STATUS_DOT[agentStatus] ?? 'bg-text-muted'

  return (
    <div className="flex flex-col h-full overflow-hidden bg-bg-panel">
      {/* Header */}
      <div className="panel-header">
        <span className={clsx('w-1.5 h-1.5 rounded-full flex-shrink-0', dotClass)} />
        <span className="flex-1 truncate">◈ Agent Logs — {agentName}</span>
        <span
          className={clsx(
            'font-mono text-[0.52rem] px-1 py-px border rounded-sm flex-shrink-0',
            agentStatus === 'RUNNING' ? 'text-positive border-positive'
            : agentStatus === 'PAUSED' ? 'text-warning border-warning'
            : agentStatus === 'ERROR'  ? 'text-negative border-negative'
            : 'text-text-muted border-border-subtle'
          )}
        >
          {agentStatus}
        </span>
        <span className="font-mono text-[0.52rem] text-text-muted flex-shrink-0">
          {filtered.length}/{displayLogs.length} lines
        </span>
        {onClose && (
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors text-[0.8rem] ml-1 flex-shrink-0"
            aria-label="Close log viewer"
          >
            ✕
          </button>
        )}
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-0 px-2 py-1.5 border-b border-border-subtle bg-bg-panel flex-shrink-0 flex-wrap gap-y-1">
        {/* Level filter buttons */}
        <div className="flex items-center gap-0 mr-2">
          {LEVEL_FILTERS.map(f => (
            <button
              key={f}
              onClick={() => setLevelFilter(f)}
              className={clsx(
                'px-2 py-0.5 font-mono text-[0.55rem] uppercase tracking-wide border-b-2 transition-colors',
                levelFilter === f
                  ? 'text-accent-cyan border-b-accent-cyan'
                  : 'text-text-muted border-b-transparent hover:text-text-secondary'
              )}
            >
              {f}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="flex items-center gap-1 flex-1 min-w-[100px] bg-bg-panel-raised border border-border-subtle rounded-sm px-1.5 py-0.5 mr-2">
          <Search size={9} className="text-text-muted flex-shrink-0" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search logs..."
            className="bg-transparent border-none outline-none font-mono text-[0.6rem] text-text-primary placeholder:text-text-muted w-full"
            aria-label="Search logs"
          />
          {search && (
            <button onClick={() => setSearch('')} className="text-text-muted hover:text-text-secondary text-[0.6rem]">
              ✕
            </button>
          )}
        </div>

        {/* Auto-scroll toggle */}
        <button
          onClick={() => setAutoScroll(v => !v)}
          className={clsx(
            'flex items-center gap-1 px-1.5 py-0.5 font-mono text-[0.55rem] border rounded-sm transition-colors mr-1',
            autoScroll
              ? 'border-accent-cyan text-accent-cyan'
              : 'border-border-subtle text-text-muted hover:text-text-secondary'
          )}
          title="Toggle auto-scroll"
          aria-pressed={autoScroll}
        >
          {autoScroll ? <ChevronDown size={9} /> : <ChevronUp size={9} />}
          AUTO
        </button>

        {/* Clear */}
        <button
          onClick={() => {/* logs are prop-controlled; in real impl would call parent */}}
          className="flex items-center gap-1 px-1.5 py-0.5 font-mono text-[0.55rem] border border-border-subtle text-text-muted hover:text-text-secondary rounded-sm transition-colors mr-1"
          title="Clear logs"
          aria-label="Clear logs"
        >
          <Trash2 size={9} />
          CLEAR
        </button>

        {/* Export */}
        <button
          onClick={handleExport}
          className="flex items-center gap-1 px-1.5 py-0.5 font-mono text-[0.55rem] border border-border-subtle text-text-muted hover:text-accent-cyan rounded-sm transition-colors"
          title="Export logs as .txt"
          aria-label="Export logs"
        >
          <Download size={9} />
          EXPORT
        </button>
      </div>

      {/* Log output area */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto bg-bg-root min-h-0 font-mono text-[0.62rem]"
        role="log"
        aria-live="polite"
        aria-label="Agent log output"
      >
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-full text-text-muted font-mono text-[0.62rem]">
            {displayLogs.length === 0 ? 'Waiting for logs...' : 'No logs match filter'}
          </div>
        ) : (
          <table className="w-full border-collapse">
            <tbody>
              {filtered.map(entry => {
                const lc = LEVEL_CONFIG[entry.level]
                return (
                  <tr
                    key={entry.id}
                    className={clsx(
                      'border-b border-border-muted hover:bg-bg-panel-raised group transition-colors',
                    )}
                  >
                    {/* Timestamp */}
                    <td className="pl-2 pr-2 py-px text-text-muted whitespace-nowrap align-top w-[90px] select-none">
                      {formatTs(entry.timestamp)}
                    </td>
                    {/* Level badge */}
                    <td className="pr-2 py-px whitespace-nowrap align-top w-[50px]">
                      <span className={clsx('px-0.5 rounded-sm text-[0.55rem]', lc.color, lc.bg)}>
                        {lc.label}
                      </span>
                    </td>
                    {/* Message */}
                    <td className="pr-3 py-px align-top">
                      <span className={clsx('leading-relaxed', lc.color)}>
                        {entry.message}
                      </span>
                      {entry.data && (
                        <span className="text-text-muted ml-2 text-[0.55rem]">
                          {JSON.stringify(entry.data)}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

import React, { useState, useEffect } from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { RefreshCw, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ────────────────────────────────────────────────────────────────────

type ExceptionType = 'BROKER_ERROR' | 'API_TIMEOUT' | 'VALIDATION_FAILED' | 'RISK_BLOCKED'
type ExceptionStatus = 'PENDING' | 'RETRYING' | 'DISMISSED'

export interface ExceptionItem {
  id: string
  timestamp: Date
  type: ExceptionType
  errorMessage: string
  retryCount: number
  maxRetries: number
  status: ExceptionStatus
  context?: string
}

/**
 * Props for ExceptionQueuePanel.
 * @prop exceptions - Exception queue items.
 * @prop onRetry    - Called with item id when user retries.
 * @prop onDismiss  - Called with item id when user dismisses.
 * @prop onRetryAll - Called when user retries all.
 * @prop loading    - Show skeleton loading state.
 */
export interface ExceptionQueuePanelProps {
  exceptions?: ExceptionItem[]
  onRetry?: (id: string) => void
  onDismiss?: (id: string) => void
  onRetryAll?: () => void
  loading?: boolean
}

// ── Exception type styles ─────────────────────────────────────────────────────

const EX_TYPE_STYLE: Record<ExceptionType, { label: string; cls: string }> = {
  BROKER_ERROR:      { label: 'BROKER',     cls: 'text-negative border-negative-dim bg-negative-bg' },
  API_TIMEOUT:       { label: 'TIMEOUT',    cls: 'text-warning border-warning-dim bg-warning-bg' },
  VALIDATION_FAILED: { label: 'VALIDATION', cls: 'text-accent-cyan border-[rgba(255,102,0,0.3)] bg-[rgba(255,102,0,0.1)]' },
  RISK_BLOCKED:      { label: 'RISK',       cls: 'text-text-secondary border-border-subtle bg-bg-panel-raised' },
}

// ── Group exceptions by type ──────────────────────────────────────────────────

function groupByType(items: ExceptionItem[]): Map<ExceptionType, ExceptionItem[]> {
  const map = new Map<ExceptionType, ExceptionItem[]>()
  items.forEach(item => {
    const existing = map.get(item.type) ?? []
    existing.push(item)
    map.set(item.type, existing)
  })
  return map
}

// ── Single exception row ──────────────────────────────────────────────────────

function ExceptionRow({
  item,
  onRetry,
  onDismiss,
}: {
  item: ExceptionItem
  onRetry: () => void
  onDismiss: () => void
}) {
  const [retrying, setRetrying] = useState(false)
  const ts = EX_TYPE_STYLE[item.type]
  const ago = formatDistanceToNow(item.timestamp, { addSuffix: true })
  const canRetry = item.maxRetries > 0 && item.retryCount < item.maxRetries

  const handleRetry = () => {
    setRetrying(true)
    setTimeout(() => {
      onRetry()
      setRetrying(false)
    }, 600)
  }

  return (
    <div className="flex items-start gap-2.5 px-2.5 py-2 border-b border-border-muted hover:bg-bg-panel-hover transition-colors">
      {/* Type badge */}
      <span className={clsx('font-mono text-[0.48rem] px-1 py-px border rounded-sm flex-shrink-0 mt-0.5', ts.cls)}>
        {ts.label}
      </span>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="font-mono text-[0.62rem] text-text-primary leading-relaxed">
          {item.errorMessage}
        </p>
        <div className="flex items-center gap-2 mt-1">
          {item.context && (
            <span className="font-mono text-[0.52rem] text-text-muted bg-bg-panel-raised border border-border-subtle px-1 py-px rounded-sm">
              {item.context}
            </span>
          )}
          {item.maxRetries > 0 && (
            <span className="font-mono text-[0.5rem] text-text-muted">
              {item.retryCount}/{item.maxRetries} retries
            </span>
          )}
          <span className="font-mono text-[0.48rem] text-text-muted">{ago}</span>
        </div>
        {item.maxRetries > 0 && (
          <div className="flex gap-0.5 mt-1">
            {Array.from({ length: item.maxRetries }).map((_, i) => (
              <div
                key={i}
                className={clsx(
                  'w-3 h-1 rounded-none',
                  i < item.retryCount ? 'bg-accent-cyan' : 'bg-bg-panel-raised border border-border-subtle',
                )}
              />
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 flex-shrink-0 mt-0.5">
        {canRetry && (
          <button
            onClick={handleRetry}
            disabled={retrying}
            className={clsx(
              'font-mono text-[0.55rem] px-1.5 py-0.5 rounded-sm border transition-all flex items-center gap-1',
              'text-accent-cyan border-[rgba(255,102,0,0.3)] bg-[rgba(255,102,0,0.08)]',
              'hover:bg-[rgba(255,102,0,0.15)]',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            <RefreshCw size={7} className={clsx(retrying && 'animate-spin')} />
            RETRY
          </button>
        )}
        <button
          onClick={onDismiss}
          className="font-mono text-[0.55rem] px-1.5 py-0.5 rounded-sm border border-border-subtle text-text-muted hover:text-negative hover:border-negative-dim transition-colors flex items-center gap-1"
        >
          <X size={7} />
          DISMISS
        </button>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

const VALID_EXCEPTION_TYPES = new Set<ExceptionType>([
  'BROKER_ERROR', 'API_TIMEOUT', 'VALIDATION_FAILED', 'RISK_BLOCKED',
])

function toExceptionType(raw: string | undefined): ExceptionType {
  const up = (raw ?? '').toUpperCase() as ExceptionType
  return VALID_EXCEPTION_TYPES.has(up) ? up : 'BROKER_ERROR'
}

export default function ExceptionQueuePanel({
  exceptions: propExceptions,
  onRetry,
  onDismiss,
  onRetryAll,
  loading: propLoading = false,
}: ExceptionQueuePanelProps) {
  const { data: auditItems = [], isLoading: fetchLoading } = useQuery({
    queryKey: ['audit-exceptions'],
    queryFn: () => apiGet<any[]>(API.auditLog),
    refetchInterval: 30_000,
    placeholderData: [],
  })
  const loading = propLoading || fetchLoading

  const auditMapped: ExceptionItem[] = auditItems.map(item => ({
    id: item.event_id ?? item.id ?? crypto.randomUUID(),
    type: toExceptionType(item.event_type),
    errorMessage: item.message ?? item.description ?? item.event_type ?? 'Unknown error',
    retryCount: item.retry_count ?? 0,
    maxRetries: item.max_retries ?? 0,
    status: (item.resolved ? 'DISMISSED' : 'PENDING') as ExceptionStatus,
    context: item.symbol ?? item.payload?.symbol ?? item.source ?? undefined,
    timestamp: new Date(item.occurred_at ?? item.created_at ?? Date.now()),
  }))

  const [exceptions, setExceptions] = useState<ExceptionItem[]>([])

  useEffect(() => {
    if (propExceptions) {
      setExceptions(propExceptions)
    } else {
      setExceptions(auditMapped)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditItems, propExceptions])

  const handleRetry = (id: string) => {
    onRetry?.(id)
    setExceptions(prev =>
      prev.map(e => e.id === id ? { ...e, retryCount: e.retryCount + 1 } : e)
    )
  }

  const handleDismiss = (id: string) => {
    onDismiss?.(id)
    setExceptions(prev => prev.filter(e => e.id !== id))
  }

  const handleRetryAll = () => {
    onRetryAll?.()
    setExceptions(prev =>
      prev.map(e => e.maxRetries > 0 && e.retryCount < e.maxRetries
        ? { ...e, retryCount: e.retryCount + 1 }
        : e,
      )
    )
  }

  const grouped = groupByType(exceptions)
  const pending = exceptions.filter(e => e.status === 'PENDING')

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header"><span>◈ Exception Queue</span></div>
        <div className="p-2 space-y-1.5">
          {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-16 skeleton rounded-sm" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Exception Queue</span>
        {pending.length > 0 && (
          <span className="font-mono text-[0.58rem] bg-negative text-white px-1.5 py-px rounded-sm font-bold">
            {pending.length}
          </span>
        )}
        {exceptions.some(e => e.maxRetries > 0 && e.retryCount < e.maxRetries) && (
          <button
            onClick={handleRetryAll}
            className="font-mono text-[0.55rem] text-accent-cyan hover:underline flex items-center gap-1 ml-2"
          >
            <RefreshCw size={8} />
            Retry All
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {exceptions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <span className="font-mono text-lg text-positive opacity-60">✓</span>
            <span className="font-mono text-[0.65rem] text-text-muted">No exceptions</span>
          </div>
        ) : (
          /* Render by group */
          Array.from(grouped.entries()).map(([type, items]) => {
            const ts = EX_TYPE_STYLE[type]
            return (
              <div key={type}>
                {/* Group header */}
                <div className="flex items-center gap-2 px-2.5 py-1 bg-bg-panel-raised border-b border-border-subtle">
                  <span className={clsx('font-mono text-[0.52rem] px-1 py-px border rounded-sm', ts.cls)}>
                    {ts.label}
                  </span>
                  <span className="font-mono text-[0.55rem] text-text-muted">{items.length} item{items.length > 1 ? 's' : ''}</span>
                </div>
                {items.map(item => (
                  <ExceptionRow
                    key={item.id}
                    item={item}
                    onRetry={() => handleRetry(item.id)}
                    onDismiss={() => handleDismiss(item.id)}
                  />
                ))}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

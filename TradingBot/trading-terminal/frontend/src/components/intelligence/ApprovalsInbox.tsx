import React, { useState, useEffect, useCallback, useRef } from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { CheckCircle } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useApprovals } from '@/hooks/useApprovals'
import { apiPost } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { QK } from '@/lib/queryKeys'

// ── Types ────────────────────────────────────────────────────────────────────

type AgentCategory = 'ALGO' | 'DISC' | 'AI' | 'QUANT'
type SignalDirection = 'BUY' | 'SELL'
type OrderType = 'MARKET' | 'LIMIT' | 'STOP_LIMIT'

export interface PendingApproval {
  id: string
  agentName: string
  agentCategory: AgentCategory
  ticker: string
  direction: SignalDirection
  confidence: number
  qty: number
  estimatedValue: number
  orderType: OrderType
  limitPrice?: number
  portfolioPct: number
  estimatedMaxLoss: number
  rawSignal: string
  timestamp: Date
}

/**
 * Props for ApprovalsInbox.
 * @prop approvals  - Pending approval entries.
 * @prop onApprove  - Called with approval id when user approves.
 * @prop onReject   - Called with approval id when user rejects.
 * @prop loading    - Show skeleton loading state.
 */
export interface ApprovalsInboxProps {
  approvals?: PendingApproval[]
  onApprove?: (id: string) => void
  onReject?: (id: string) => void
  loading?: boolean
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtValue(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000)     return `$${(v / 1_000).toFixed(1)}K`
  return `$${v.toFixed(0)}`
}

const AGENT_CAT_STYLE: Record<AgentCategory, string> = {
  ALGO:  'bg-[rgba(255,102,0,0.15)] text-accent-cyan border border-[rgba(255,102,0,0.3)]',
  DISC:  'bg-[rgba(171,71,188,0.15)] text-accent-purple border border-[rgba(171,71,188,0.3)]',
  AI:    'bg-warning-bg text-warning border border-warning-dim',
  QUANT: 'bg-info-bg text-info border border-info-dim',
}

// ── Approval card ─────────────────────────────────────────────────────────────

type CardState = 'idle' | 'approving' | 'rejecting' | 'done'

function ApprovalCard({
  approval,
  focused,
  onApprove,
  onReject,
}: {
  approval: PendingApproval
  focused: boolean
  onApprove: () => void
  onReject: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [state, setState] = useState<CardState>('idle')
  const isBuy = approval.direction === 'BUY'
  const ago = formatDistanceToNow(approval.timestamp, { addSuffix: true })

  const handleApprove = () => {
    setState('approving')
    setTimeout(onApprove, 400)
  }

  const handleReject = () => {
    setState('rejecting')
    setTimeout(onReject, 400)
  }

  return (
    <div
      className={clsx(
        'border-b border-border-subtle transition-all',
        focused && 'bg-[rgba(255,102,0,0.03)]',
        state === 'approving' && 'opacity-50 bg-positive-bg',
        state === 'rejecting' && 'opacity-50 bg-negative-bg',
      )}
    >
      <div className="px-3 py-2.5">
        {/* Row 1: Agent + direction + ticker + time */}
        <div className="flex items-center gap-2 mb-2">
          <span className={clsx('font-mono text-[0.52rem] px-1.5 py-px rounded-sm', AGENT_CAT_STYLE[approval.agentCategory])}>
            {approval.agentCategory}
          </span>
          <span className="font-mono text-[0.65rem] text-text-secondary">{approval.agentName}</span>
          <div className="flex-1" />
          <span className="font-mono text-[0.52rem] text-text-muted">{ago}</span>
          {focused && (
            <span className="font-mono text-[0.48rem] bg-[rgba(255,102,0,0.15)] text-accent-cyan border border-[rgba(255,102,0,0.3)] px-1 py-px rounded-sm">
              FOCUSED
            </span>
          )}
        </div>

        {/* Row 2: Signal details */}
        <div className="flex items-center gap-3 mb-2">
          <span className="font-mono text-xl font-bold text-accent-cyan">{approval.ticker}</span>
          <span className={clsx(
            'font-mono text-sm font-bold px-2 py-0.5 border rounded-sm',
            isBuy ? 'text-positive border-positive-dim bg-positive-bg' : 'text-negative border-negative-dim bg-negative-bg',
          )}>
            {approval.direction}
          </span>
          <span className={clsx(
            'font-mono text-[0.7rem] font-semibold tabular-nums',
            approval.confidence >= 85 ? 'text-positive' :
            approval.confidence >= 65 ? 'text-warning' : 'text-text-secondary',
          )}>
            {approval.confidence}% conf
          </span>
        </div>

        {/* Row 3: Order details */}
        <div className="flex items-center gap-4 mb-2 px-1">
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[0.5rem] text-text-muted uppercase tracking-wider">Qty</span>
            <span className="font-mono text-[0.68rem] text-text-primary tabular-nums">{approval.qty.toLocaleString()} shs</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[0.5rem] text-text-muted uppercase tracking-wider">Est. Value</span>
            <span className="font-mono text-[0.68rem] text-text-primary tabular-nums">{fmtValue(approval.estimatedValue)}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[0.5rem] text-text-muted uppercase tracking-wider">Order</span>
            <span className="font-mono text-[0.68rem] text-text-secondary">
              {approval.orderType}{approval.limitPrice ? ` @ $${approval.limitPrice.toFixed(2)}` : ''}
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[0.5rem] text-text-muted uppercase tracking-wider">Port %</span>
            <span className={clsx(
              'font-mono text-[0.68rem] tabular-nums',
              approval.portfolioPct > 5 ? 'text-warning' : 'text-text-secondary',
            )}>
              {approval.portfolioPct.toFixed(1)}%
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[0.5rem] text-text-muted uppercase tracking-wider">Max Loss</span>
            <span className="font-mono text-[0.68rem] text-negative tabular-nums">{fmtValue(approval.estimatedMaxLoss)}</span>
          </div>
        </div>

        {/* Raw signal — truncated by default */}
        <div className="mb-2">
          <button
            onClick={() => setExpanded(e => !e)}
            className="w-full text-left"
          >
            <p className={clsx(
              'font-mono text-[0.6rem] text-text-muted leading-relaxed',
              !expanded && 'line-clamp-2',
            )}>
              {approval.rawSignal}
            </p>
            <span className="font-mono text-[0.52rem] text-accent-cyan mt-0.5 block">
              {expanded ? '▲ Collapse' : '▼ Expand signal'}
            </span>
          </button>
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 mt-1">
          <button
            onClick={handleApprove}
            disabled={state !== 'idle'}
            className={clsx(
              'flex-1 font-mono text-[0.72rem] font-bold py-2 rounded-sm border transition-all',
              'text-positive border-positive-dim bg-positive-bg',
              'hover:bg-[rgba(0,230,118,0.2)] hover:shadow-glow-green',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            ✓ APPROVE {focused && <span className="opacity-60">(A)</span>}
          </button>
          <button
            onClick={handleReject}
            disabled={state !== 'idle'}
            className={clsx(
              'flex-1 font-mono text-[0.72rem] font-bold py-2 rounded-sm border transition-all',
              'text-negative border-negative-dim bg-negative-bg',
              'hover:bg-[rgba(255,23,68,0.2)] hover:shadow-glow-red',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            ✗ REJECT {focused && <span className="opacity-60">(R)</span>}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ApprovalsInbox({
  approvals: propApprovals,
  onApprove: propOnApprove,
  onReject: propOnReject,
  loading: propLoading = false,
}: ApprovalsInboxProps) {
  const { approvals: liveApprovals, isLoading: fetchLoading } = useApprovals()
  const queryClient = useQueryClient()
  const loading = propLoading || fetchLoading

  // Map API Approval to component's PendingApproval shape
  const mappedApprovals: PendingApproval[] = (propApprovals ?? liveApprovals).map(a => ({
    id: a.id,
    agentName: (a as any).agentName ?? 'Unknown Agent',
    agentCategory: 'ALGO' as const,
    ticker: (a as any).symbol ?? 'N/A',
    direction: ((a as any).direction ?? 'BUY') as 'BUY' | 'SELL',
    confidence: Math.round(((a as any).confidence ?? 0) * 100),
    qty: (a as any).qty ?? 0,
    estimatedValue: (a as any).estimatedValue ?? 0,
    orderType: (((a as any).orderType ?? 'MARKET') as 'MARKET' | 'LIMIT' | 'STOP_LIMIT'),
    limitPrice: (a as any).limitPrice ?? undefined,
    portfolioPct: (a as any).portfolioPct ?? 0,
    estimatedMaxLoss: (a as any).estimatedMaxLoss ?? 0,
    rawSignal: (a as any).rawSignal ?? '',
    timestamp: new Date((a as any).requestedAt ?? Date.now()),
  }))

  const defaultApprove = async (id: string) => {
    await apiPost(API.approveSignal(id))
    void queryClient.invalidateQueries({ queryKey: QK.approvals })
  }

  const defaultReject = async (id: string) => {
    await apiPost(API.rejectSignal(id))
    void queryClient.invalidateQueries({ queryKey: QK.approvals })
  }

  const [approvals, setApprovals] = useState<PendingApproval[]>([])
  const [focusedIdx, setFocusedIdx] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)

  // Sync from mapped data
  useEffect(() => {
    setApprovals(mappedApprovals)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveApprovals, propApprovals])

  const handleApprove = useCallback((id: string) => {
    const fn = propOnApprove ?? defaultApprove
    void fn(id)
    setApprovals(prev => prev.filter(a => a.id !== id))
    setFocusedIdx(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propOnApprove])

  const handleReject = useCallback((id: string) => {
    const fn = propOnReject ?? defaultReject
    void fn(id)
    setApprovals(prev => prev.filter(a => a.id !== id))
    setFocusedIdx(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propOnReject])

  // Keyboard shortcuts: A = approve focused, R = reject focused
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      const focused = approvals[focusedIdx]
      if (!focused) return
      if (e.key === 'a' || e.key === 'A') handleApprove(focused.id)
      if (e.key === 'r' || e.key === 'R') handleReject(focused.id)
      if (e.key === 'ArrowDown') setFocusedIdx(i => Math.min(i + 1, approvals.length - 1))
      if (e.key === 'ArrowUp') setFocusedIdx(i => Math.max(i - 1, 0))
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [approvals, focusedIdx, handleApprove, handleReject])

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header"><span>◈ Approvals Inbox</span></div>
        <div className="p-2 space-y-2">
          {Array.from({ length: 2 }).map((_, i) => <div key={i} className="h-32 skeleton rounded-sm" />)}
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Approvals Inbox</span>
        {approvals.length > 0 && (
          <span className="font-mono text-[0.6rem] bg-negative text-white px-1.5 py-px rounded-sm font-bold animate-pulse">
            {approvals.length}
          </span>
        )}
        <span className="font-mono text-[0.5rem] text-text-muted ml-1">A/R keys</span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {approvals.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 py-8">
            <CheckCircle size={28} className="text-positive opacity-60" />
            <div className="text-center">
              <p className="font-mono text-[0.72rem] text-positive font-semibold">All Clear</p>
              <p className="font-mono text-[0.6rem] text-text-muted mt-0.5">No pending approvals</p>
            </div>
          </div>
        ) : (
          approvals.map((approval, idx) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              focused={idx === focusedIdx}
              onApprove={() => handleApprove(approval.id)}
              onReject={() => handleReject(approval.id)}
            />
          ))
        )}
      </div>
    </div>
  )
}

import React, { useState } from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { useLiveSignals } from '@/hooks/useLiveSignals'

// ── Types ────────────────────────────────────────────────────────────────────

type AgentCategory = 'ALGO' | 'DISC' | 'AI'
type SignalDirection = 'BUY' | 'SELL'

interface ContributingAgent {
  id: string
  name: string
  category: AgentCategory
  message: string
}

export interface ConfluenceSignal {
  id: string
  ticker: string
  direction: SignalDirection
  agreementCount: number
  totalAgents: number
  confidence: number
  agents: ContributingAgent[]
  timestamp: Date
}

/**
 * Props for ConfluencePanel.
 * @prop signals - Array of confluence signals. Defaults to mock data.
 * @prop loading - Shows skeleton loading state when true.
 */
export interface ConfluencePanelProps {
  signals?: ConfluenceSignal[]
  loading?: boolean
}

// ── Agent category pills ──────────────────────────────────────────────────────

const AGENT_CAT_STYLE: Record<AgentCategory, string> = {
  ALGO:  'bg-[rgba(255,102,0,0.15)] text-accent-cyan border border-[rgba(255,102,0,0.3)]',
  DISC:  'bg-[rgba(171,71,188,0.15)] text-accent-purple border border-[rgba(171,71,188,0.3)]',
  AI:    'bg-warning-bg text-warning border border-warning-dim',
}

function AgentPill({ agent }: { agent: ContributingAgent }) {
  return (
    <span
      className={clsx(
        'font-mono text-[0.5rem] px-1 py-px rounded-sm flex-shrink-0',
        AGENT_CAT_STYLE[agent.category],
      )}
    >
      {agent.category}
    </span>
  )
}

// ── Direction badge ───────────────────────────────────────────────────────────

function DirectionBadge({ direction }: { direction: SignalDirection }) {
  return (
    <span
      className={clsx(
        'font-mono text-[0.6rem] font-bold px-1.5 py-px border rounded-sm',
        direction === 'BUY'
          ? 'text-positive border-positive-dim bg-positive-bg'
          : 'text-negative border-negative-dim bg-negative-bg',
      )}
    >
      {direction}
    </span>
  )
}

// ── Agreement bar ────────────────────────────────────────────────────────────

function AgreementBar({
  count,
  total,
  direction,
}: {
  count: number
  total: number
  direction: SignalDirection
}) {
  const filled = Math.round((count / total) * 7)
  const color = direction === 'BUY' ? 'bg-positive' : 'bg-negative'
  const emptyColor = 'bg-border-subtle'
  return (
    <div className="flex gap-0.5 items-center">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className={clsx('w-3 h-1.5 rounded-none', i < filled ? color : emptyColor)}
        />
      ))}
    </div>
  )
}

// ── Confidence bar ────────────────────────────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
  const color =
    value >= 85 ? 'bg-positive' :
    value >= 65 ? 'bg-warning' :
    'bg-accent-cyan'
  return (
    <div className="h-1 bg-bg-panel-raised overflow-hidden w-16">
      <div className={clsx('h-full', color)} style={{ width: `${value}%` }} />
    </div>
  )
}

// ── Signal row ────────────────────────────────────────────────────────────────

function SignalRow({
  signal,
  expanded,
  onToggle,
}: {
  signal: ConfluenceSignal
  expanded: boolean
  onToggle: () => void
}) {
  const ago = formatDistanceToNow(signal.timestamp, { addSuffix: true })
  return (
    <>
      <div
        className={clsx(
          'flex items-center gap-2 px-2.5 py-2 cursor-pointer border-b border-border-muted transition-colors',
          expanded ? 'bg-[rgba(255,102,0,0.04)]' : 'hover:bg-bg-panel-hover',
        )}
        onClick={onToggle}
      >
        {/* Ticker */}
        <span className="font-mono text-[0.72rem] font-bold text-accent-cyan w-12 flex-shrink-0">
          {signal.ticker}
        </span>

        {/* Direction */}
        <DirectionBadge direction={signal.direction} />

        {/* Agreement count */}
        <span className="font-mono text-[0.62rem] text-text-secondary tabular-nums flex-shrink-0">
          {signal.agreementCount}/{signal.totalAgents}
          <span className="text-text-muted ml-1">agents</span>
        </span>

        {/* Agreement bar */}
        <AgreementBar
          count={signal.agreementCount}
          total={signal.totalAgents}
          direction={signal.direction}
        />

        <div className="flex-1" />

        {/* Confidence */}
        <div className="flex flex-col items-end gap-0.5 flex-shrink-0">
          <span
            className={clsx(
              'font-mono text-[0.65rem] font-semibold tabular-nums',
              signal.confidence >= 85 ? 'text-positive' :
              signal.confidence >= 65 ? 'text-warning' : 'text-text-secondary',
            )}
          >
            {signal.confidence}%
          </span>
          <ConfidenceBar value={signal.confidence} />
        </div>

        {/* Agent pills */}
        <div className="flex gap-0.5 flex-shrink-0">
          {(['ALGO', 'DISC', 'AI'] as AgentCategory[]).map(cat => {
            const has = signal.agents.some(a => a.category === cat)
            return has ? (
              <span key={cat} className={clsx('font-mono text-[0.5rem] px-1 py-px rounded-sm', AGENT_CAT_STYLE[cat])}>
                {cat}
              </span>
            ) : null
          })}
        </div>

        {/* Time */}
        <span className="font-mono text-[0.52rem] text-text-muted flex-shrink-0">{ago}</span>

        {/* Expand chevron */}
        <span className="font-mono text-[0.6rem] text-text-muted flex-shrink-0">
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {/* Expanded: contributing signals */}
      {expanded && (
        <div className="bg-bg-panel-raised border-b border-border-subtle px-3 py-2">
          <div className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-1.5">
            Contributing Agents
          </div>
          <div className="space-y-1.5">
            {signal.agents.map(agent => (
              <div key={agent.id} className="flex items-start gap-2">
                <AgentPill agent={agent} />
                <span className="font-mono text-[0.55rem] text-text-muted flex-shrink-0">
                  {agent.name}
                </span>
                <span className="font-mono text-[0.6rem] text-text-secondary leading-relaxed">
                  {agent.message}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ConfluencePanel({
  signals: propSignals,
  loading: propLoading = false,
}: ConfluencePanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const { signals: rawSignals, isLoading: fetchLoading } = useLiveSignals()
  const loading = propLoading || fetchLoading

  const liveSignals: ConfluenceSignal[] = (rawSignals ?? []).map(s => ({
    id: (s as any).id ?? (s as any).signal_id ?? crypto.randomUUID(),
    ticker: (s as any).symbol ?? (s as any).ticker ?? 'N/A',
    direction: ((s as any).direction ?? 'BUY') as 'BUY' | 'SELL',
    agreementCount: 1,
    totalAgents: 1,
    confidence: Math.round(((s as any).confidence ?? 0) * 100),
    agents: [{
      id: (s as any).source ?? 'system',
      name: (s as any).source ?? 'System',
      category: 'ALGO' as const,
      message: (s as any).raw_text ?? (s as any).message ?? `${(s as any).direction} signal`,
    }],
    timestamp: new Date((s as any).created_at ?? Date.now()),
  }))

  const signals = propSignals ?? liveSignals

  const sorted = [...signals].sort((a, b) => {
    if (b.agreementCount !== a.agreementCount) return b.agreementCount - a.agreementCount
    return b.confidence - a.confidence
  })

  const activeCount = sorted.length

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header">
          <span className="flex-1">◈ Confluence Signals</span>
        </div>
        <div className="p-2 space-y-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-8 skeleton rounded-sm" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Confluence Signals</span>
        {activeCount > 0 && (
          <span className="font-mono text-[0.55rem] bg-accent-cyan text-bg-root px-1.5 py-px rounded-sm font-bold">
            {activeCount}
          </span>
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0">
        {(['ALGO', 'DISC', 'AI'] as AgentCategory[]).map(cat => (
          <div key={cat} className="flex items-center gap-1">
            <span className={clsx('font-mono text-[0.5rem] px-1 py-px rounded-sm', AGENT_CAT_STYLE[cat])}>
              {cat}
            </span>
          </div>
        ))}
        <span className="font-mono text-[0.52rem] text-text-muted ml-auto">3+ agents required</span>
      </div>

      {/* Feed */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 py-8">
            <span className="font-mono text-lg text-text-muted">◈</span>
            <span className="font-mono text-[0.65rem] text-text-muted">
              Waiting for 3+ agent agreement...
            </span>
          </div>
        ) : (
          sorted.map(signal => (
            <SignalRow
              key={signal.id}
              signal={signal}
              expanded={expandedId === signal.id}
              onToggle={() => setExpandedId(expandedId === signal.id ? null : signal.id)}
            />
          ))
        )}
      </div>
    </div>
  )
}

import React, { useMemo, useState } from 'react'
import clsx from 'clsx'
import { useLiveFleet } from '@/hooks/useLiveFleet'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AgentRow {
  name: string
  category: string
  todayPnl: number
  totalPnl: number
  winRate: number
  signals: number
}

export interface AgentAttributionPanelProps {
  agents?: AgentRow[]
  loading?: boolean
}

type SortMode = 'pnl' | 'winrate' | 'signals'


// ── Sparkline Mini ────────────────────────────────────────────────────────────

interface SparkbarProps {
  values: number[]
  height?: number
}

function Sparkbar({ values, height = 24 }: SparkbarProps) {
  const max = Math.max(...values.map(Math.abs), 1)
  return (
    <div className="flex items-end gap-px" style={{ height }}>
      {values.map((v, i) => (
        <div
          key={i}
          className={clsx('flex-1 min-w-[2px]', v >= 0 ? 'bg-positive' : 'bg-negative')}
          style={{ height: `${(Math.abs(v) / max) * 100}%`, opacity: 0.75 }}
        />
      ))}
    </div>
  )
}

// ── Category Badge ────────────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  TREND: 'text-accent-cyan border-accent-cyan/40',
  REVERT: 'text-accent-purple border-accent-purple/40',
  BREAK: 'text-warning border-warning/40',
  VOL: 'text-accent-amber border-accent-amber/40',
  SCALP: 'text-info border-info/40',
  EVENT: 'text-text-secondary border-border-subtle',
  FLOW: 'text-positive border-positive/40',
  MACRO: 'text-text-secondary border-border-subtle',
  SECTOR: 'text-accent-purple border-accent-purple/40',
  NEWS: 'text-warning border-warning/40',
  ARBI: 'text-info border-info/40',
}

function CategoryBadge({ cat }: { cat: string }) {
  const cls = CATEGORY_COLORS[cat] ?? 'text-text-secondary border-border-subtle'
  return (
    <span className={clsx('px-1 py-0 text-[0.5rem] border font-mono tracking-widest', cls)}>
      {cat}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function AgentAttributionPanel({
  agents,
  loading = false,
}: AgentAttributionPanelProps) {
  const [sortMode, setSortMode] = useState<SortMode>('pnl')
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null)

  const { agents: fleetAgents } = useLiveFleet()

  const liveRows: AgentRow[] = fleetAgents.map(a => ({
    name: a.displayName ?? a.name,
    category: a.category,
    todayPnl: a.metrics?.todayPnl ?? 0,
    totalPnl: a.metrics?.totalPnl ?? 0,
    winRate: (a.metrics?.winRate ?? 0) * 100,
    signals: a.metrics?.totalSignals ?? 0,
  }))

  const rows = agents ?? (liveRows.length > 0 ? liveRows : [])

  const sorted = useMemo(() => {
    const copy = [...rows]
    if (sortMode === 'pnl') copy.sort((a, b) => b.totalPnl - a.totalPnl)
    else if (sortMode === 'winrate') copy.sort((a, b) => b.winRate - a.winRate)
    else copy.sort((a, b) => b.signals - a.signals)
    return copy
  }, [rows, sortMode])

  const totalPnl = rows.reduce((s, r) => s + r.totalPnl, 0)
  const todayTotal = rows.reduce((s, r) => s + r.todayPnl, 0)
  const maxAbsPnl = Math.max(...rows.map((r) => Math.abs(r.totalPnl)), 1)

  function getMockSparkline(name: string): number[] {
    // Deterministic mock from name hash
    let seed = name.split('').reduce((a, c) => a + c.charCodeAt(0), 0)
    return Array.from({ length: 20 }, () => {
      seed = (seed * 1664525 + 1013904223) & 0xffffffff
      return ((seed >>> 0) % 2000) - 900
    })
  }

  if (loading) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ AGENT ATTRIBUTION</div>
        <div className="flex-1 skeleton m-2 rounded-sm" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
      {/* Header */}
      <div className="panel-header flex-shrink-0">
        <span>◈ AGENT ATTRIBUTION</span>
        <span
          className={clsx(
            'ml-2 text-[0.6rem] font-mono tabular-nums',
            totalPnl >= 0 ? 'text-positive' : 'text-negative',
          )}
        >
          {totalPnl >= 0 ? '+' : ''}
          {totalPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {(['pnl', 'winrate', 'signals'] as SortMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setSortMode(m)}
              className={clsx(
                'px-1.5 py-0.5 text-[0.55rem] font-mono tracking-wider border transition-colors',
                sortMode === m
                  ? 'border-accent-cyan text-accent-cyan bg-accent-cyan/10'
                  : 'border-border-subtle text-text-muted hover:text-text-secondary',
              )}
            >
              {m === 'pnl' ? 'P&L' : m === 'winrate' ? 'WIN%' : 'SIG'}
            </button>
          ))}
        </div>
      </div>

      {/* Table header */}
      <div className="flex items-center gap-1 px-2 py-1 border-b border-border-subtle bg-bg-panel-raised flex-shrink-0">
        <span className="w-28 text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">Agent</span>
        <span className="flex-1 text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">Contribution</span>
        <span className="w-16 text-right text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">Today</span>
        <span className="w-16 text-right text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">Total</span>
        <span className="w-12 text-right text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">Win%</span>
      </div>

      {/* Rows */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {sorted.map((agent) => {
          const barPct = (Math.abs(agent.totalPnl) / maxAbsPnl) * 100
          const isExpanded = expandedAgent === agent.name
          return (
            <div key={agent.name} className="border-b border-border-muted">
              <button
                className="w-full flex items-center gap-1 px-2 py-1 hover:bg-bg-panel-hover transition-colors text-left"
                onClick={() => setExpandedAgent(isExpanded ? null : agent.name)}
              >
                {/* Name + badge */}
                <div className="w-28 flex flex-col gap-0.5 min-w-0">
                  <span className="text-[0.62rem] font-mono text-text-primary truncate">{agent.name}</span>
                  <CategoryBadge cat={agent.category} />
                </div>
                {/* Bar */}
                <div className="flex-1 relative h-3 bg-bg-panel-raised rounded-sm overflow-hidden">
                  <div
                    className={clsx(
                      'h-full rounded-sm transition-all duration-300',
                      agent.totalPnl >= 0 ? 'bg-positive/50' : 'bg-negative/50',
                    )}
                    style={{ width: `${barPct}%` }}
                  />
                </div>
                {/* Today */}
                <span
                  className={clsx(
                    'w-16 text-right text-[0.62rem] font-mono tabular-nums',
                    agent.todayPnl >= 0 ? 'text-positive' : 'text-negative',
                  )}
                >
                  {agent.todayPnl >= 0 ? '+' : ''}
                  {agent.todayPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}
                </span>
                {/* Total */}
                <span
                  className={clsx(
                    'w-16 text-right text-[0.62rem] font-mono tabular-nums',
                    agent.totalPnl >= 0 ? 'text-positive' : 'text-negative',
                  )}
                >
                  {agent.totalPnl >= 0 ? '+' : ''}
                  {agent.totalPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}
                </span>
                {/* Win Rate */}
                <span
                  className={clsx(
                    'w-12 text-right text-[0.62rem] font-mono tabular-nums',
                    agent.winRate >= 65 ? 'text-positive' : agent.winRate >= 50 ? 'text-warning' : 'text-negative',
                  )}
                >
                  {agent.winRate.toFixed(1)}%
                </span>
              </button>

              {/* Expanded sparkline */}
              {isExpanded && (
                <div className="px-2 pb-2 bg-bg-panel-raised border-t border-border-muted">
                  <div className="flex items-center justify-between mb-1 pt-1">
                    <span className="text-[0.55rem] font-mono text-text-muted uppercase tracking-widest">
                      Daily P&L — last 20 sessions
                    </span>
                    <span className="text-[0.55rem] font-mono text-text-muted">
                      {agent.signals} signals
                    </span>
                  </div>
                  <Sparkbar values={getMockSparkline(agent.name)} height={32} />
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Totals Row */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-t border-border-subtle bg-bg-panel-raised flex-shrink-0">
        <span className="w-28 text-[0.6rem] font-mono text-text-secondary uppercase tracking-widest">TOTAL</span>
        <div className="flex-1" />
        <span
          className={clsx(
            'w-16 text-right text-[0.62rem] font-mono tabular-nums font-semibold',
            todayTotal >= 0 ? 'text-positive' : 'text-negative',
          )}
        >
          {todayTotal >= 0 ? '+' : ''}
          {todayTotal.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}
        </span>
        <span
          className={clsx(
            'w-16 text-right text-[0.62rem] font-mono tabular-nums font-semibold',
            totalPnl >= 0 ? 'text-positive' : 'text-negative',
          )}
        >
          {totalPnl >= 0 ? '+' : ''}
          {totalPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}
        </span>
        <span className="w-12 text-right text-[0.62rem] font-mono text-text-muted">
          {(rows.reduce((s, r) => s + r.winRate, 0) / rows.length).toFixed(1)}%
        </span>
      </div>
    </div>
  )
}

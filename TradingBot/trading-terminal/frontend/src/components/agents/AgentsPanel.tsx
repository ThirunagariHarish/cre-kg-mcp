import React, { useState, useMemo } from 'react'
import clsx from 'clsx'
import { formatDistanceToNow, format } from 'date-fns'
import {
  Play, Pause, Square, AlertTriangle, CheckCircle,
  Activity, TrendingUp, TrendingDown, Clock, Zap,
  ChevronRight, ChevronDown, Circle, RefreshCw, Plus,
} from 'lucide-react'
import type { Agent, AgentCategory, AgentStatus } from '@/types/agents'
import AgentPerformanceSparkline from './AgentPerformanceSparkline'
import AgentStatusModal from './AgentStatusModal'
import AgentCreationWizard from './AgentCreationWizard'
import AgentDependencyGraph from './AgentDependencyGraph'
import { useLiveFleet } from '@/hooks/useLiveFleet'

/* ─────────────────────────────────────────────
   Helper components
───────────────────────────────────────────── */

const STATUS_CONFIG: Record<AgentStatus, { dot: string; label: string; text: string }> = {
  RUNNING: { dot: 'bg-positive',     label: '● RUN',    text: 'text-positive' },
  PAUSED:  { dot: 'bg-warning',      label: '⏸ PAUSE',  text: 'text-warning' },
  STOPPED: { dot: 'bg-text-muted',   label: '■ STOP',   text: 'text-text-muted' },
  ERROR:   { dot: 'bg-negative',     label: '✕ ERROR',  text: 'text-negative' },
  IDLE:    { dot: 'bg-accent-amber', label: '○ IDLE',   text: 'text-accent-amber' },
}

const CAT_CONFIG: Record<AgentCategory, { label: string; color: string }> = {
  ALGORITHM: { label: 'ALGO',  color: 'text-accent-cyan border-accent-cyan' },
  DISCORD:   { label: 'DISC',  color: 'text-accent-purple border-accent-purple' },
  AI:        { label: 'AI',    color: 'text-accent-amber border-accent-amber' },
  DATA:      { label: 'DATA',  color: 'text-info border-info' },
  PORTFOLIO: { label: 'PORT',  color: 'text-text-secondary border-border-subtle' },
  OPTIONS:   { label: 'OPTS',  color: 'text-positive border-positive-dim' },
}

function StatusBadge({ status }: { status: AgentStatus }) {
  const c = STATUS_CONFIG[status]
  return (
    <span className={clsx('flex items-center gap-1 font-mono text-[0.58rem]', c.text)}>
      <span className={clsx('w-1.5 h-1.5 rounded-full flex-shrink-0', c.dot)} />
      {status}
    </span>
  )
}

function CategoryBadge({ cat }: { cat: AgentCategory }) {
  const c = CAT_CONFIG[cat]
  return (
    <span className={clsx('font-mono text-[0.55rem] px-1 py-px border rounded-sm flex-shrink-0', c.color)}>
      {c.label}
    </span>
  )
}

function PnlSpan({ value }: { value: number }) {
  if (value === 0) return <span className="font-mono text-[0.7rem] text-text-muted tabular-nums">—</span>
  const positive = value >= 0
  return (
    <span className={clsx('font-mono text-[0.7rem] tabular-nums font-semibold', positive ? 'text-positive' : 'text-negative')}>
      {positive ? '+' : '-'}${Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: 0 })}
    </span>
  )
}

function WinRateBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100)
  const color = pct >= 70 ? 'bg-positive' : pct >= 55 ? 'bg-warning' : 'bg-negative'
  const textColor = pct >= 70 ? 'text-positive' : pct >= 55 ? 'text-warning' : 'text-negative'
  return (
    <div className="flex items-center gap-1.5 flex-1 max-w-[80px]">
      <div className="flex-1 h-1 bg-bg-panel-raised rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className={clsx('font-mono text-[0.65rem] tabular-nums flex-shrink-0 w-7 text-right', textColor)}>
        {pct}%
      </span>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Agent Detail Panel
───────────────────────────────────────────── */

function AgentDetail({ agent, onClose, onStart, onStop, onPause }: {
  agent: Agent
  onClose: () => void
  onStart?: () => void
  onStop?: () => void
  onPause?: () => void
}) {
  const sc = STATUS_CONFIG[agent.status]
  const cc = CAT_CONFIG[agent.category]
  const winPct = Math.round(agent.metrics.winRate * 100)

  return (
    <div className="flex flex-col h-full overflow-hidden border-l border-border-subtle bg-bg-panel">
      {/* Detail Header */}
      <div className="panel-header">
        <span className={clsx('flex items-center gap-1.5 flex-1', sc.text)}>
          <span className={clsx('w-1.5 h-1.5 rounded-full', sc.dot)} />
          {agent.displayName}
        </span>
        <CategoryBadge cat={agent.category} />
        <button onClick={onClose} className="ml-2 text-text-muted hover:text-text-primary transition-colors text-[0.8rem]">✕</button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Description */}
        <div className="px-3 py-2 border-b border-border-subtle">
          <p className="font-mono text-[0.62rem] text-text-secondary leading-relaxed">
            {agent.config.description || agent.config.notes}
          </p>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-px bg-border-subtle border-b border-border-subtle">
          {[
            { label: 'Signals', value: agent.metrics.totalSignals.toString() },
            { label: 'Win Rate', value: `${winPct}%`, color: winPct >= 70 ? 'text-positive' : winPct >= 55 ? 'text-warning' : 'text-negative' },
            { label: 'Total P&L', value: agent.metrics.totalPnl > 0 ? `+$${agent.metrics.totalPnl.toLocaleString()}` : agent.metrics.totalPnl < 0 ? `-$${Math.abs(agent.metrics.totalPnl).toLocaleString()}` : '—', color: agent.metrics.totalPnl >= 0 ? 'text-positive' : 'text-negative' },
            { label: 'Today P&L', value: agent.metrics.todayPnl > 0 ? `+$${agent.metrics.todayPnl.toLocaleString()}` : agent.metrics.todayPnl < 0 ? `-$${Math.abs(agent.metrics.todayPnl).toLocaleString()}` : '—', color: agent.metrics.todayPnl >= 0 ? 'text-positive' : 'text-negative' },
            { label: 'Trades', value: agent.metrics.executedTrades.toString() },
            { label: 'Avg Hold', value: `${agent.metrics.avgHoldMinutes}m` },
          ].map(({ label, value, color }) => (
            <div key={label} className="flex flex-col px-3 py-2 bg-bg-panel">
              <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-wider mb-0.5">{label}</span>
              <span className={clsx('font-mono text-[0.75rem] tabular-nums font-semibold', color ?? 'text-text-primary')}>{value}</span>
            </div>
          ))}
        </div>

        {/* Config */}
        <div className="px-3 py-2 border-b border-border-subtle">
          <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1.5">Config</p>
          {[
            { k: 'Mode', v: agent.config.trading_mode },
            { k: 'Scan Interval', v: agent.config.scan_interval_seconds ? `${agent.config.scan_interval_seconds}s` : '—' },
            { k: 'Stop Loss', v: agent.config.stop_loss_pct ? `${agent.config.stop_loss_pct}%` : '—' },
            { k: 'Profit Target', v: agent.config.profit_target_pct ? `${agent.config.profit_target_pct}%` : '—' },
            { k: 'Max Daily', v: agent.config.max_daily_trades ? `${agent.config.max_daily_trades} trades` : '—' },
            { k: 'Confidence', v: agent.config.confidence_threshold ? `${(agent.config.confidence_threshold * 100).toFixed(0)}%` : '—' },
          ].map(({ k, v }) => (
            <div key={k} className="flex justify-between py-0.5">
              <span className="font-mono text-[0.58rem] text-text-muted">{k}</span>
              <span className="font-mono text-[0.62rem] text-text-secondary">{v ?? '—'}</span>
            </div>
          ))}
        </div>

        {/* Activity Log */}
        <div className="px-3 py-2">
          <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1.5">Recent Activity</p>
          <div className="space-y-1.5">
            {agent.recentActivity.map(a => {
              const typeColor = a.type === 'TRADE'
                ? (a.pnl !== undefined && a.pnl >= 0 ? 'text-positive' : a.pnl !== undefined ? 'text-negative' : 'text-text-secondary')
                : a.type === 'SIGNAL' ? 'text-accent-cyan'
                : a.type === 'ERROR' ? 'text-negative'
                : a.type === 'STATUS' ? 'text-warning'
                : 'text-text-muted'
              return (
                <div key={a.id} className="flex items-start gap-2">
                  <span className="font-mono text-[0.55rem] text-text-muted tabular-nums flex-shrink-0 mt-px">
                    {formatDistanceToNow(a.timestamp, { addSuffix: true })}
                  </span>
                  <span className={clsx('font-mono text-[0.6rem] leading-relaxed', typeColor)}>
                    {a.ticker && <span className="text-accent-cyan">[{a.ticker}] </span>}
                    {a.message}
                    {a.pnl !== undefined && <span className={a.pnl >= 0 ? 'text-positive' : 'text-negative'}> ({a.pnl >= 0 ? '+' : ''}${a.pnl})</span>}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="flex gap-1.5 p-2.5 border-t border-border-subtle flex-shrink-0">
        {agent.status === 'RUNNING' ? (
          <>
            <button
              onClick={onPause}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 font-mono text-[0.62rem] border border-warning text-warning hover:bg-warning-bg rounded-sm transition-colors"
              aria-label="Pause agent"
            >
              <Pause size={9} /> PAUSE
            </button>
            <button
              onClick={onStop}
              className="flex items-center justify-center gap-1 px-2.5 py-1.5 font-mono text-[0.62rem] border border-negative text-negative hover:bg-negative-bg rounded-sm transition-colors"
              aria-label="Stop agent"
            >
              <Square size={9} /> STOP
            </button>
          </>
        ) : agent.status === 'PAUSED' ? (
          <>
            <button
              onClick={onStart}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 font-mono text-[0.62rem] border border-positive text-positive hover:bg-positive-bg rounded-sm transition-colors"
              aria-label="Resume agent"
            >
              <Play size={9} /> RESUME
            </button>
            <button
              onClick={onStop}
              className="flex items-center justify-center gap-1 px-2.5 py-1.5 font-mono text-[0.62rem] border border-negative text-negative hover:bg-negative-bg rounded-sm transition-colors"
              aria-label="Stop agent"
            >
              <Square size={9} /> STOP
            </button>
          </>
        ) : (
          <button
            onClick={onStart}
            className="flex-1 flex items-center justify-center gap-1 py-1.5 font-mono text-[0.62rem] border border-positive text-positive hover:bg-positive-bg rounded-sm transition-colors"
            aria-label="Start agent"
          >
            <Play size={9} /> START
          </button>
        )}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   7-day sparkline seed (deterministic per agent)
───────────────────────────────────────────── */

function seededRand(seed: number): () => number {
  let s = seed
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff
    return (s >>> 0) / 0xffffffff
  }
}

function makeSparklineData(agent: Agent): number[] {
  const rng = seededRand(agent.id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0))
  const totalPnl = agent.metrics.totalPnl
  // Generate 7 daily values that sum approximately to totalPnl
  const raw = Array.from({ length: 7 }, () => (rng() - 0.45) * (Math.abs(totalPnl) / 4 + 50))
  if (totalPnl !== 0) {
    const sum = raw.reduce((a, b) => a + b, 0)
    const scale = sum !== 0 ? totalPnl / sum : 1
    return raw.map(v => Math.round(v * scale * 0.4))
  }
  return raw.map(v => Math.round(v))
}

/* ─────────────────────────────────────────────
   Agent Row
───────────────────────────────────────────── */

function AgentRow({
  agent,
  selected,
  onSelect,
  onNameClick,
}: {
  agent: Agent
  selected: boolean
  onSelect: () => void
  onNameClick: (e: React.MouseEvent) => void
}) {
  const sc = STATUS_CONFIG[agent.status]
  const lastSig = agent.metrics.lastSignalAt
    ? formatDistanceToNow(agent.metrics.lastSignalAt, { addSuffix: true })
    : '—'
  const sparkData = makeSparklineData(agent)

  return (
    <tr
      className={clsx('cursor-pointer group border-b border-border-muted transition-colors', selected ? 'selected' : '')}
      onClick={onSelect}
    >
      {/* Status dot */}
      <td className="pl-2.5 pr-1 py-2.5">
        <span className={clsx('w-1.5 h-1.5 rounded-full inline-block', sc.dot)} />
      </td>
      {/* Name */}
      <td className="pr-2 py-2.5">
        <div className="flex items-center gap-1.5">
          <CategoryBadge cat={agent.category} />
          <button
            className={clsx(
              'font-mono text-[0.7rem] font-semibold hover:underline underline-offset-2 text-left',
              selected ? 'text-accent-cyan' : 'text-text-primary hover:text-accent-cyan'
            )}
            onClick={onNameClick}
            aria-label={`Open detail for ${agent.displayName}`}
          >
            {agent.displayName}
          </button>
        </div>
        {agent.config.notes && (
          <p className="font-mono text-[0.55rem] text-text-muted truncate mt-0.5 max-w-[260px]">
            {agent.config.notes.slice(0, 70)}
          </p>
        )}
      </td>
      {/* Status */}
      <td className="px-2 py-2.5">
        <StatusBadge status={agent.status} />
      </td>
      {/* Signals */}
      <td className="px-2 py-2.5 text-right font-mono text-[0.7rem] tabular-nums text-text-secondary">
        {agent.metrics.totalSignals}
      </td>
      {/* Win Rate */}
      <td className="px-2 py-2.5">
        {agent.metrics.totalSignals > 0 ? (
          <WinRateBar rate={agent.metrics.winRate} />
        ) : (
          <span className="font-mono text-[0.65rem] text-text-muted">—</span>
        )}
      </td>
      {/* Today P&L */}
      <td className="px-2 py-2.5 text-right">
        <PnlSpan value={agent.metrics.todayPnl} />
      </td>
      {/* Total P&L */}
      <td className="px-2 py-2.5 text-right">
        <PnlSpan value={agent.metrics.totalPnl} />
      </td>
      {/* 7-day sparkline */}
      <td className="px-2 py-2.5 hidden lg:table-cell">
        <AgentPerformanceSparkline data={sparkData} width={60} height={20} />
      </td>
      {/* Last signal */}
      <td className="px-2 pr-3 py-2.5 text-right font-mono text-[0.58rem] text-text-muted hidden xl:table-cell">
        {lastSig}
      </td>
    </tr>
  )
}

/* ─────────────────────────────────────────────
   Summary Bar
───────────────────────────────────────────── */

function SummaryBar({ agents }: { agents: Agent[] }) {
  const running = agents.filter(a => a.status === 'RUNNING').length
  const paused  = agents.filter(a => a.status === 'PAUSED').length
  const errors  = agents.filter(a => a.status === 'ERROR').length
  const todayPnl = agents.reduce((s, a) => s + a.metrics.todayPnl, 0)
  const totalPnl = agents.reduce((s, a) => s + a.metrics.totalPnl, 0)
  const totalSigs = agents.reduce((s, a) => s + a.metrics.totalSignals, 0)

  return (
    <div className="flex items-center gap-4 px-3 py-2 border-b border-border-subtle bg-bg-panel flex-shrink-0 overflow-x-auto">
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-positive" />
        <span className="font-mono text-[0.62rem] text-positive">{running} RUNNING</span>
      </div>
      {paused > 0 && (
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-warning" />
          <span className="font-mono text-[0.62rem] text-warning">{paused} PAUSED</span>
        </div>
      )}
      {errors > 0 && (
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-negative animate-pulse" />
          <span className="font-mono text-[0.62rem] text-negative">{errors} ERROR</span>
        </div>
      )}
      <div className="w-px h-3 bg-border-subtle flex-shrink-0" />
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <span className="font-mono text-[0.6rem] text-text-muted">SIGNALS</span>
        <span className="font-mono text-[0.68rem] text-text-primary">{totalSigs}</span>
      </div>
      <div className="w-px h-3 bg-border-subtle flex-shrink-0" />
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <span className="font-mono text-[0.6rem] text-text-muted">TODAY</span>
        <span className={clsx('font-mono text-[0.68rem] font-semibold tabular-nums', todayPnl >= 0 ? 'text-positive' : 'text-negative')}>
          {todayPnl >= 0 ? '+' : '-'}${Math.abs(todayPnl).toLocaleString()}
        </span>
      </div>
      <div className="w-px h-3 bg-border-subtle flex-shrink-0" />
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <span className="font-mono text-[0.6rem] text-text-muted">TOTAL</span>
        <span className={clsx('font-mono text-[0.68rem] font-semibold tabular-nums', totalPnl >= 0 ? 'text-positive' : 'text-negative')}>
          {totalPnl >= 0 ? '+' : '-'}${Math.abs(totalPnl).toLocaleString()}
        </span>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Main Panel
───────────────────────────────────────────── */

type FilterCategory = AgentCategory | 'ALL'

const CAT_FILTERS: FilterCategory[] = ['ALL', 'ALGORITHM', 'DISCORD', 'AI', 'OPTIONS', 'PORTFOLIO', 'DATA']

export default function AgentsPanel() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [modalAgentId, setModalAgentId] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterCategory>('ALL')
  const [statusFilter, setStatusFilter] = useState<AgentStatus | null>(null)
  const [search, setSearch] = useState('')
  const [showWizard, setShowWizard] = useState(false)
  const [showDepGraph, setShowDepGraph] = useState(false)

  const { agents: liveAgents } = useLiveFleet()

  const selected = liveAgents.find(a => a.id === selectedId) ?? null
  const modalAgent = liveAgents.find(a => a.id === modalAgentId) ?? null

  const filtered = useMemo(() => {
    return liveAgents.filter(a => {
      if (filter !== 'ALL' && a.category !== filter) return false
      if (statusFilter && a.status !== statusFilter) return false
      if (search && !a.displayName.toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }, [liveAgents, filter, statusFilter, search])

  return (
    <>
      <div className="flex h-full overflow-hidden">
        {/* ── Agent List ── */}
        <div className={clsx('flex flex-col overflow-hidden', selected ? 'flex-1' : 'w-full')}>
          {/* Panel header */}
          <div className="panel-header">
            <Activity size={10} className="flex-shrink-0" />
            <span className="flex-1">◈ Agents</span>
            <span className="font-mono text-[0.55rem] text-text-muted">{liveAgents.length} agents</span>
            <button
              onClick={() => setShowWizard(true)}
              className="flex items-center gap-1 ml-2 px-1.5 py-0.5 font-mono text-[0.55rem] border border-accent-cyan text-accent-cyan hover:bg-bg-panel-raised rounded-sm transition-colors flex-shrink-0"
              aria-label="Create new agent"
            >
              <Plus size={8} />
              NEW AGENT
            </button>
          </div>

          {/* Summary bar */}
          <SummaryBar agents={liveAgents} />

          {/* Filters */}
          <div className="flex items-center gap-0 border-b border-border-subtle flex-shrink-0 overflow-x-auto bg-bg-panel">
            {CAT_FILTERS.map(cat => (
              <button
                key={cat}
                onClick={() => setFilter(cat)}
                className={clsx(
                  'px-2.5 py-1.5 font-mono text-[0.58rem] uppercase tracking-wide flex-shrink-0 border-b-2 transition-colors',
                  filter === cat
                    ? 'text-accent-cyan border-b-accent-cyan'
                    : 'text-text-muted border-b-transparent hover:text-text-secondary'
                )}
              >
                {cat}
              </button>
            ))}
            <button
              onClick={() => setShowDepGraph(prev => !prev)}
              className={clsx(
                'px-2.5 py-1.5 font-mono text-[0.58rem] uppercase tracking-wide flex-shrink-0 border-b-2 transition-colors',
                showDepGraph
                  ? 'text-accent-cyan border-b-accent-cyan bg-bg-panel-raised'
                  : 'text-text-muted border-b-transparent hover:text-text-secondary'
              )}
              aria-label="Toggle dependency graph"
            >
              DEP MAP
            </button>
            <div className="flex-1" />
            {/* Status quick filters */}
            {(['RUNNING', 'PAUSED', 'ERROR'] as AgentStatus[]).map(s => {
              const c = STATUS_CONFIG[s]
              return (
                <button
                  key={s}
                  onClick={() => setStatusFilter(statusFilter === s ? null : s)}
                  className={clsx(
                    'flex items-center gap-1 px-2 py-1.5 font-mono text-[0.55rem] flex-shrink-0',
                    statusFilter === s ? c.text : 'text-text-muted hover:text-text-secondary'
                  )}
                >
                  <span className={clsx('w-1.5 h-1.5 rounded-full', c.dot)} />
                  {liveAgents.filter(a => a.status === s).length}
                </button>
              )
            })}
            <div className="px-2">
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Filter..."
                className="bg-transparent border-none outline-none font-mono text-[0.62rem] text-text-primary placeholder:text-text-muted w-20"
              />
            </div>
          </div>

          {/* Table or Dependency Graph */}
          {showDepGraph ? (
            <div className="flex-1 overflow-hidden min-h-0">
              <AgentDependencyGraph />
            </div>
          ) : (
            <div className="flex-1 overflow-auto min-h-0">
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="w-6 text-left pl-2.5"></th>
                    <th className="text-left pl-0">Name</th>
                    <th className="text-left">Status</th>
                    <th>Signals</th>
                    <th>Win %</th>
                    <th>Today P&L</th>
                    <th>Total P&L</th>
                    <th className="hidden lg:table-cell text-left">7D</th>
                    <th className="hidden xl:table-cell">Last Signal</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="text-center py-8 text-text-muted">
                        No agents match filter
                      </td>
                    </tr>
                  ) : (
                    filtered.map(agent => (
                      <AgentRow
                        key={agent.id}
                        agent={agent}
                        selected={agent.id === selectedId}
                        onSelect={() => setSelectedId(agent.id === selectedId ? null : agent.id)}
                        onNameClick={e => {
                          e.stopPropagation()
                          setModalAgentId(agent.id)
                        }}
                      />
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Agent Detail ── */}
        {selected && (
          <div className="w-72 flex-shrink-0">
            <AgentDetail
              agent={selected}
              onClose={() => setSelectedId(null)}
              onStart={() => { /* wire to real handler in production */ }}
              onStop={() => { /* wire to real handler in production */ }}
              onPause={() => { /* wire to real handler in production */ }}
            />
          </div>
        )}
      </div>

      {/* ── Agent Status Modal ── */}
      {modalAgent && (
        <AgentStatusModal
          agent={modalAgent}
          onClose={() => setModalAgentId(null)}
          onStart={() => { /* wire to real handler */ }}
          onStop={() => { /* wire to real handler */ }}
          onPause={() => { /* wire to real handler */ }}
        />
      )}

      {/* ── Agent Creation Wizard Modal ── */}
      {showWizard && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
          role="dialog"
          aria-modal="true"
          aria-label="Create new agent"
        >
          <div className="w-[520px] max-w-[95vw] h-[620px] max-h-[90vh] rounded-sm shadow-panel-active overflow-hidden">
            <AgentCreationWizard
              onComplete={() => setShowWizard(false)}
              onCancel={() => setShowWizard(false)}
            />
          </div>
        </div>
      )}
    </>
  )
}

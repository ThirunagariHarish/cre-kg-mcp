import React, { useEffect, useState, useCallback } from 'react'
import clsx from 'clsx'
import { Play, Pause, Square, X } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import type { Agent, AgentCategory, AgentStatus } from '@/types/agents'
import AgentLogViewer from './AgentLogViewer'
import AgentTimelinePanel from './AgentTimelinePanel'

/* ─────────────────────────────────────────────
   Props
───────────────────────────────────────────── */

interface AgentStatusModalProps {
  /** The agent to display */
  agent: Agent
  /** Close the modal */
  onClose: () => void
  /** Start a stopped/idle/paused agent */
  onStart?: () => void
  /** Stop a running agent */
  onStop?: () => void
  /** Pause a running agent */
  onPause?: () => void
}

/* ─────────────────────────────────────────────
   Config maps
───────────────────────────────────────────── */

const STATUS_CONFIG: Record<AgentStatus, { dot: string; text: string; label: string }> = {
  RUNNING: { dot: 'bg-positive animate-pulse', text: 'text-positive', label: 'RUNNING' },
  PAUSED:  { dot: 'bg-warning',                text: 'text-warning',  label: 'PAUSED' },
  STOPPED: { dot: 'bg-text-muted',             text: 'text-text-muted', label: 'STOPPED' },
  ERROR:   { dot: 'bg-negative animate-pulse', text: 'text-negative', label: 'ERROR' },
  IDLE:    { dot: 'bg-accent-amber',           text: 'text-accent-amber', label: 'IDLE' },
}

const CAT_CONFIG: Record<AgentCategory, { label: string; color: string }> = {
  ALGORITHM: { label: 'ALGO',  color: 'text-accent-cyan border-accent-cyan' },
  DISCORD:   { label: 'DISC',  color: 'text-accent-purple border-accent-purple' },
  AI:        { label: 'AI',    color: 'text-accent-amber border-accent-amber' },
  DATA:      { label: 'DATA',  color: 'text-info border-info' },
  PORTFOLIO: { label: 'PORT',  color: 'text-text-secondary border-border-subtle' },
  OPTIONS:   { label: 'OPTS',  color: 'text-positive border-positive-dim' },
}

/* ─────────────────────────────────────────────
   Tab: Overview
───────────────────────────────────────────── */

function OverviewTab({ agent }: { agent: Agent }) {
  const winPct = Math.round(agent.metrics.winRate * 100)

  const stats = [
    { label: 'Total Signals', value: agent.metrics.totalSignals.toString() },
    { label: 'Win Rate',     value: `${winPct}%`, color: winPct >= 70 ? 'text-positive' : winPct >= 55 ? 'text-warning' : 'text-negative' },
    { label: 'Total P&L',   value: agent.metrics.totalPnl !== 0 ? `${agent.metrics.totalPnl >= 0 ? '+' : '-'}$${Math.abs(agent.metrics.totalPnl).toLocaleString()}` : '—', color: agent.metrics.totalPnl >= 0 ? 'text-positive' : 'text-negative' },
    { label: 'Today P&L',   value: agent.metrics.todayPnl !== 0 ? `${agent.metrics.todayPnl >= 0 ? '+' : '-'}$${Math.abs(agent.metrics.todayPnl).toLocaleString()}` : '—', color: agent.metrics.todayPnl >= 0 ? 'text-positive' : 'text-negative' },
    { label: 'Trades',      value: agent.metrics.executedTrades.toString() },
    { label: 'Avg Hold',    value: `${agent.metrics.avgHoldMinutes}m` },
  ]

  const config = [
    { k: 'Mode',          v: agent.config.trading_mode ?? '—' },
    { k: 'Scan Interval', v: agent.config.scan_interval_seconds ? `${agent.config.scan_interval_seconds}s` : '—' },
    { k: 'Stop Loss',     v: agent.config.stop_loss_pct ? `${agent.config.stop_loss_pct}%` : '—' },
    { k: 'Profit Target', v: agent.config.profit_target_pct ? `${agent.config.profit_target_pct}%` : '—' },
    { k: 'Max Daily',     v: agent.config.max_daily_trades ? `${agent.config.max_daily_trades} trades` : '—' },
    { k: 'Confidence',    v: agent.config.confidence_threshold ? `${(agent.config.confidence_threshold <= 1 ? agent.config.confidence_threshold * 100 : agent.config.confidence_threshold).toFixed(0)}%` : '—' },
    { k: 'Broker',        v: agent.config.broker ?? '—' },
    { k: 'Signal Source', v: agent.config.signal_source ?? '—' },
  ]

  return (
    <div className="flex-1 overflow-y-auto min-h-0 p-4 space-y-4">
      {/* Description */}
      {(agent.config.description || agent.config.notes) && (
        <div className="bg-bg-panel-raised border border-border-subtle rounded-sm p-3">
          <p className="font-mono text-[0.6rem] text-text-secondary leading-relaxed">
            {agent.config.description || agent.config.notes}
          </p>
        </div>
      )}

      {/* Stats grid */}
      <div>
        <p className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-2">Performance</p>
        <div className="grid grid-cols-3 gap-px bg-border-subtle border border-border-subtle rounded-sm overflow-hidden">
          {stats.map(({ label, value, color }) => (
            <div key={label} className="flex flex-col px-3 py-2.5 bg-bg-panel">
              <span className="font-mono text-[0.52rem] text-text-muted uppercase tracking-wider mb-0.5">{label}</span>
              <span className={clsx('font-mono text-[0.78rem] tabular-nums font-semibold', color ?? 'text-text-primary')}>
                {value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Config summary */}
      <div>
        <p className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-2">Configuration</p>
        <div className="bg-bg-panel-raised border border-border-subtle rounded-sm overflow-hidden">
          <div className="grid grid-cols-2">
            {config.map(({ k, v }) => (
              <div key={k} className="flex justify-between px-3 py-1.5 border-b border-border-subtle last:border-b-0">
                <span className="font-mono text-[0.58rem] text-text-muted">{k}</span>
                <span className="font-mono text-[0.62rem] text-text-secondary tabular-nums">{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Activity log */}
      <div>
        <p className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-2">Recent Activity</p>
        <div className="space-y-1.5">
          {agent.recentActivity.length === 0 ? (
            <p className="font-mono text-[0.6rem] text-text-muted">No recent activity</p>
          ) : (
            agent.recentActivity.map(a => {
              const typeColor = a.type === 'TRADE'
                ? (a.pnl != null && a.pnl >= 0 ? 'text-positive' : a.pnl != null ? 'text-negative' : 'text-info')
                : a.type === 'SIGNAL' ? 'text-accent-cyan'
                : a.type === 'ERROR' ? 'text-negative'
                : a.type === 'STATUS' ? 'text-warning'
                : 'text-text-muted'
              return (
                <div key={a.id} className="flex items-start gap-2 py-1 border-b border-border-muted last:border-b-0">
                  <span className="font-mono text-[0.52rem] text-text-muted tabular-nums flex-shrink-0 mt-px w-16">
                    {formatDistanceToNow(a.timestamp, { addSuffix: true })}
                  </span>
                  <span className={clsx('font-mono text-[0.6rem] leading-relaxed', typeColor)}>
                    {a.ticker && <span className="text-accent-cyan">[{a.ticker}] </span>}
                    {a.message}
                    {a.pnl != null && (
                      <span className={a.pnl >= 0 ? 'text-positive' : 'text-negative'}>
                        {' '}({a.pnl >= 0 ? '+' : ''}${a.pnl})
                      </span>
                    )}
                  </span>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Main Modal
───────────────────────────────────────────── */

type TabId = 'overview' | 'logs' | 'timeline'

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'logs',     label: 'Logs' },
  { id: 'timeline', label: 'Timeline' },
]

export default function AgentStatusModal({
  agent,
  onClose,
  onStart,
  onStop,
  onPause,
}: AgentStatusModalProps) {
  const [tab, setTab] = useState<TabId>('overview')

  const sc = STATUS_CONFIG[agent.status]
  const cc = CAT_CONFIG[agent.category]

  // Escape key closes
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  // Prevent scroll on body
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  const handleBackdropClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose()
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-bg-root/85 backdrop-blur-sm animate-fade-in"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-label={`Agent detail: ${agent.displayName}`}
    >
      <div
        className="relative flex flex-col bg-bg-panel border border-border-subtle shadow-panel-active rounded-sm overflow-hidden animate-slide-in-up"
        style={{ width: 'min(900px, 96vw)', height: 'min(680px, 92vh)' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border-subtle flex-shrink-0 bg-bg-panel">
          {/* Status dot */}
          <span className={clsx('w-2 h-2 rounded-full flex-shrink-0', sc.dot)} />

          {/* Agent name + category */}
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <span className="font-mono text-[0.85rem] font-semibold text-text-primary truncate">
              {agent.displayName}
            </span>
            <span className={clsx('font-mono text-[0.55rem] px-1.5 py-px border rounded-sm flex-shrink-0', cc.color)}>
              {cc.label}
            </span>
            <span className={clsx('font-mono text-[0.58rem] flex-shrink-0', sc.text)}>
              {sc.label}
            </span>
          </div>

          {/* Agent version */}
          {agent.version != null && (
            <span className="font-mono text-[0.52rem] text-text-muted flex-shrink-0">v{agent.version}</span>
          )}

          {/* Control buttons */}
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {agent.status === 'RUNNING' ? (
              <>
                <button
                  onClick={onPause}
                  className="flex items-center gap-1 px-2 py-1 font-mono text-[0.6rem] border border-warning text-warning hover:bg-warning-bg rounded-sm transition-colors"
                  aria-label="Pause agent"
                >
                  <Pause size={9} />
                  PAUSE
                </button>
                <button
                  onClick={onStop}
                  className="flex items-center gap-1 px-2 py-1 font-mono text-[0.6rem] border border-negative text-negative hover:bg-negative-bg rounded-sm transition-colors"
                  aria-label="Stop agent"
                >
                  <Square size={9} />
                  STOP
                </button>
              </>
            ) : agent.status === 'PAUSED' ? (
              <>
                <button
                  onClick={onStart}
                  className="flex items-center gap-1 px-2 py-1 font-mono text-[0.6rem] border border-positive text-positive hover:bg-positive-bg rounded-sm transition-colors"
                  aria-label="Resume agent"
                >
                  <Play size={9} />
                  RESUME
                </button>
                <button
                  onClick={onStop}
                  className="flex items-center gap-1 px-2 py-1 font-mono text-[0.6rem] border border-negative text-negative hover:bg-negative-bg rounded-sm transition-colors"
                  aria-label="Stop agent"
                >
                  <Square size={9} />
                  STOP
                </button>
              </>
            ) : (
              <button
                onClick={onStart}
                className="flex items-center gap-1 px-2 py-1 font-mono text-[0.6rem] border border-positive text-positive hover:bg-positive-bg rounded-sm transition-colors"
                aria-label="Start agent"
              >
                <Play size={9} />
                START
              </button>
            )}
          </div>

          {/* Close */}
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors ml-1 flex-shrink-0"
            aria-label="Close modal"
          >
            <X size={14} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-0 border-b border-border-subtle flex-shrink-0 bg-bg-panel">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={clsx(
                'px-4 py-2 font-mono text-[0.62rem] uppercase tracking-wider border-b-2 transition-colors',
                tab === t.id
                  ? 'text-accent-cyan border-b-accent-cyan'
                  : 'text-text-muted border-b-transparent hover:text-text-secondary'
              )}
              role="tab"
              aria-selected={tab === t.id}
            >
              {t.label}
            </button>
          ))}
          {/* Agent started-at info */}
          {agent.startedAt != null && (
            <span className="ml-auto mr-4 font-mono text-[0.52rem] text-text-muted">
              Started {formatDistanceToNow(agent.startedAt, { addSuffix: true })}
            </span>
          )}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-hidden min-h-0" role="tabpanel">
          {tab === 'overview' && <OverviewTab agent={agent} />}
          {tab === 'logs' && (
            <AgentLogViewer
              agentName={agent.displayName}
              agentStatus={agent.status}
            />
          )}
          {tab === 'timeline' && (
            <AgentTimelinePanel agentName={agent.displayName} />
          )}
        </div>
      </div>
    </div>
  )
}

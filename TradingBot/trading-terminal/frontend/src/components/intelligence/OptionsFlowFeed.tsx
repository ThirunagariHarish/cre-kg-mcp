import React, { useRef, useState, useEffect } from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'

// ── Types ────────────────────────────────────────────────────────────────────

type OptionType = 'CALL' | 'PUT'
type FlowSentiment = 'BULLISH' | 'BEARISH' | 'NEUTRAL'
type OrderBadge = 'SWEEP' | 'BLOCK' | null

export interface OptionsFlowEntry {
  id: string
  time: Date
  ticker: string
  strike: number
  expiry: string
  type: OptionType
  bid: number
  ask: number
  size: number
  premium: number
  openInterest: number
  sentiment: FlowSentiment
  badge: OrderBadge
}

type SizeFilter = 'ALL' | '100K' | '500K' | '1M'

/**
 * Props for OptionsFlowFeed.
 * @prop entries - Live options flow entries.
 * @prop loading - Show skeleton loading state.
 */
export interface OptionsFlowFeedProps {
  entries?: OptionsFlowEntry[]
  loading?: boolean
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPremium(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

function fmtOI(v: number): string {
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`
  return String(v)
}

const SIZE_LABELS: Record<SizeFilter, string> = {
  ALL: 'All',
  '100K': '>$100K',
  '500K': '>$500K',
  '1M': '>$1M SWEEP',
}

const SIZE_THRESHOLDS: Record<SizeFilter, number> = {
  ALL: 0,
  '100K': 100_000,
  '500K': 500_000,
  '1M': 1_000_000,
}

// ── Main component ────────────────────────────────────────────────────────────

export default function OptionsFlowFeed({
  entries = [],
  loading = false,
}: OptionsFlowFeedProps) {
  const [sizeFilter, setSizeFilter] = useState<SizeFilter>('ALL')
  const [paused, setPaused] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!paused && scrollRef.current) {
      scrollRef.current.scrollTop = 0
    }
  }, [entries, paused])

  const filtered = entries.filter(e => e.premium >= SIZE_THRESHOLDS[sizeFilter])

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header"><span>◈ Options Flow</span></div>
        <div className="p-2 space-y-1">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-6 skeleton rounded-sm" />)}
        </div>
      </div>
    )
  }

  if (!entries.length) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="panel-header"><span className="flex-1">◈ Options Flow</span></div>
        <div className="flex items-center justify-center flex-1 text-text-muted font-mono text-[0.65rem]">
          <div className="text-center">
            <div className="text-text-dim mb-1">NO DATA</div>
            <div className="text-[0.55rem]">Pending backend integration</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Options Flow</span>
        {/* Live indicator */}
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-positive animate-pulse" />
          <span className="font-mono text-[0.55rem] text-positive">LIVE</span>
        </span>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-1 px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0">
        {(Object.entries(SIZE_LABELS) as [SizeFilter, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setSizeFilter(key)}
            className={clsx(
              'font-mono text-[0.58rem] px-2 py-0.5 rounded-sm border transition-colors',
              sizeFilter === key
                ? 'bg-[rgba(255,102,0,0.1)] text-accent-cyan border-accent-cyan'
                : 'text-text-muted border-border-muted hover:border-border-subtle',
            )}
          >
            {label}
          </button>
        ))}
        <div className="flex-1" />
        <span className="font-mono text-[0.52rem] text-text-muted tabular-nums">
          {filtered.length} prints
        </span>
      </div>

      {/* Table */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto min-h-0"
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
      >
        <table className="data-table w-full">
          <thead>
            <tr>
              <th className="text-left pl-2.5">Time</th>
              <th className="text-left">Ticker</th>
              <th>Strike</th>
              <th>Exp</th>
              <th>C/P</th>
              <th>Bid×Ask</th>
              <th>Size</th>
              <th>Premium</th>
              <th>OI</th>
              <th>Sent</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(entry => {
              const isBullish = entry.sentiment === 'BULLISH'
              const isBearish = entry.sentiment === 'BEARISH'
              return (
                <tr
                  key={entry.id}
                  className={clsx(
                    'transition-colors',
                    isBullish && 'bg-[rgba(0,230,118,0.025)] hover:bg-[rgba(0,230,118,0.05)]',
                    isBearish && 'bg-[rgba(255,23,68,0.025)]  hover:bg-[rgba(255,23,68,0.05)]',
                  )}
                >
                  <td className="text-left pl-2.5 text-text-muted">
                    {entry.time.toTimeString().slice(0, 8)}
                  </td>
                  <td className="text-left font-bold text-accent-cyan">{entry.ticker}</td>
                  <td className="tabular-nums">${entry.strike}</td>
                  <td className="text-text-muted">{entry.expiry}</td>
                  <td>
                    <span
                      className={clsx(
                        'font-mono text-[0.6rem] font-bold px-1 py-px border rounded-sm',
                        entry.type === 'CALL'
                          ? 'text-positive border-positive-dim bg-positive-bg'
                          : 'text-negative border-negative-dim bg-negative-bg',
                      )}
                    >
                      {entry.type}
                    </span>
                  </td>
                  <td className="tabular-nums text-text-secondary">
                    {entry.bid.toFixed(2)}×{entry.ask.toFixed(2)}
                  </td>
                  <td className="tabular-nums">{entry.size.toLocaleString()}</td>
                  <td className={clsx('tabular-nums font-semibold', entry.premium >= 1_000_000 ? 'text-accent-cyan' : 'text-text-primary')}>
                    {fmtPremium(entry.premium)}
                  </td>
                  <td className="tabular-nums text-text-muted">{fmtOI(entry.openInterest)}</td>
                  <td>
                    <div className="flex items-center justify-end gap-1">
                      {entry.badge && (
                        <span
                          className={clsx(
                            'font-mono text-[0.48rem] px-1 py-px rounded-sm font-bold',
                            entry.badge === 'SWEEP'
                              ? 'bg-[rgba(255,102,0,0.15)] text-accent-cyan border border-[rgba(255,102,0,0.3)]'
                              : 'bg-info-bg text-info border border-info-dim',
                          )}
                        >
                          {entry.badge}
                        </span>
                      )}
                      <span
                        className={clsx(
                          'font-mono text-[0.52rem]',
                          isBullish ? 'text-positive' :
                          isBearish ? 'text-negative' : 'text-text-muted',
                        )}
                      >
                        {isBullish ? '▲' : isBearish ? '▼' : '●'}
                      </span>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <div className="flex items-center justify-center py-8">
            <span className="font-mono text-[0.65rem] text-text-muted">No flow matching filter</span>
          </div>
        )}
      </div>

      {paused && (
        <div className="px-2.5 py-1 bg-bg-panel-raised border-t border-border-subtle flex-shrink-0">
          <span className="font-mono text-[0.55rem] text-text-muted">⏸ Scroll paused (hover)</span>
        </div>
      )}
    </div>
  )
}

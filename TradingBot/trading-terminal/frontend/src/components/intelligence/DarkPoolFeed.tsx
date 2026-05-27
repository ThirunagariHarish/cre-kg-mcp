import React, { useState } from 'react'
import clsx from 'clsx'

// ── Types ────────────────────────────────────────────────────────────────────

type DarkPoolExchange = 'NYSE' | 'NASDAQ' | 'IEX' | 'FINRA' | 'BATS'
type VwapPosition = 'ABOVE' | 'BELOW' | 'AT'

export interface DarkPoolEntry {
  id: string
  time: Date
  ticker: string
  price: number
  size: number
  value: number
  exchange: DarkPoolExchange
  vwap: number
  vwapDiffPct: number
  vwapPosition: VwapPosition
}

type ValueFilter = 'ALL' | '500K' | '1M' | '5M'
type ExchangeFilter = 'ALL' | DarkPoolExchange

/**
 * Props for DarkPoolFeed.
 * @prop entries  - Dark pool print entries.
 * @prop loading  - Show skeleton loading state.
 */
export interface DarkPoolFeedProps {
  entries?: DarkPoolEntry[]
  loading?: boolean
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtValue(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

function fmtSize(v: number): string {
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`
  return String(v)
}

const VALUE_THRESHOLDS: Record<ValueFilter, number> = {
  ALL: 0,
  '500K': 500_000,
  '1M': 1_000_000,
  '5M': 5_000_000,
}

// ── Ticker repeat count ───────────────────────────────────────────────────────

function buildRepeatMap(entries: DarkPoolEntry[]): Map<string, number> {
  const map = new Map<string, number>()
  const now = Date.now()
  entries.forEach(e => {
    if (now - e.time.getTime() <= 3_600_000) {
      map.set(e.ticker, (map.get(e.ticker) ?? 0) + 1)
    }
  })
  return map
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DarkPoolFeed({
  entries = [],
  loading = false,
}: DarkPoolFeedProps) {
  const [valueFilter, setValueFilter] = useState<ValueFilter>('ALL')
  const [exchangeFilter, setExchangeFilter] = useState<ExchangeFilter>('ALL')

  const repeatMap = buildRepeatMap(entries)

  const filtered = entries.filter(e => {
    if (e.value < VALUE_THRESHOLDS[valueFilter]) return false
    if (exchangeFilter !== 'ALL' && e.exchange !== exchangeFilter) return false
    return true
  })

  const exchanges: DarkPoolExchange[] = ['NYSE', 'NASDAQ', 'IEX', 'FINRA']

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header"><span>◈ Dark Pool Prints</span></div>
        <div className="p-2 space-y-1">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-6 skeleton rounded-sm" />)}
        </div>
      </div>
    )
  }

  if (!entries.length) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="panel-header"><span className="flex-1">◈ Dark Pool Prints</span></div>
        <div className="flex items-center justify-center flex-1 text-text-muted font-mono text-[0.65rem]">
          <div className="text-center">
            <div className="text-text-dim mb-1">NO DATA</div>
            <div className="text-[0.55rem]">Dark pool data requires Unusual Whales API integration</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Dark Pool Prints</span>
        <span className="font-mono text-[0.52rem] text-text-muted tabular-nums">{filtered.length} prints</span>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-1 px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0">
        {/* Value filter */}
        {(Object.keys(VALUE_THRESHOLDS) as ValueFilter[]).map(key => (
          <button
            key={key}
            onClick={() => setValueFilter(key)}
            className={clsx(
              'font-mono text-[0.58rem] px-2 py-0.5 rounded-sm border transition-colors',
              valueFilter === key
                ? 'bg-[rgba(255,102,0,0.1)] text-accent-cyan border-accent-cyan'
                : 'text-text-muted border-border-muted hover:border-border-subtle',
            )}
          >
            {key === 'ALL' ? 'All' : `>${key}`}
          </button>
        ))}

        <div className="w-px h-3 bg-border-subtle mx-0.5" />

        {/* Exchange filter */}
        {(['ALL', ...exchanges] as (ExchangeFilter)[]).map(ex => (
          <button
            key={ex}
            onClick={() => setExchangeFilter(ex)}
            className={clsx(
              'font-mono text-[0.58rem] px-2 py-0.5 rounded-sm border transition-colors',
              exchangeFilter === ex
                ? 'bg-[rgba(255,102,0,0.1)] text-accent-cyan border-accent-cyan'
                : 'text-text-muted border-border-muted hover:border-border-subtle',
            )}
          >
            {ex}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <table className="data-table w-full">
          <thead>
            <tr>
              <th className="text-left pl-2.5">Time</th>
              <th className="text-left">Ticker</th>
              <th>Price</th>
              <th>Size</th>
              <th>Value</th>
              <th>Exch</th>
              <th>vs VWAP</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(entry => {
              const isLarge = entry.value >= 1_000_000
              const repeatCount = repeatMap.get(entry.ticker) ?? 0
              const isAbove = entry.vwapPosition === 'ABOVE'
              const isBelow = entry.vwapPosition === 'BELOW'
              return (
                <tr
                  key={entry.id}
                  className={clsx(
                    'transition-colors hover:bg-bg-panel-hover',
                    isLarge && 'border-l-2 border-l-accent-cyan',
                  )}
                >
                  <td className="text-left pl-2.5 text-text-muted">
                    {entry.time.toTimeString().slice(0, 8)}
                  </td>
                  <td className="text-left">
                    <div className="flex items-center gap-1">
                      <span className="font-bold text-accent-cyan">{entry.ticker}</span>
                      {repeatCount > 2 && (
                        <span className="font-mono text-[0.48rem] px-1 py-px rounded-sm bg-[rgba(255,102,0,0.15)] text-accent-cyan border border-[rgba(255,102,0,0.3)]">
                          ×{repeatCount}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="tabular-nums">${entry.price.toFixed(2)}</td>
                  <td className="tabular-nums text-text-secondary">{fmtSize(entry.size)}</td>
                  <td className={clsx('tabular-nums font-semibold', isLarge ? 'text-accent-cyan' : 'text-text-primary')}>
                    {fmtValue(entry.value)}
                  </td>
                  <td className="text-text-muted text-[0.58rem]">{entry.exchange}</td>
                  <td>
                    <div className="flex items-center justify-end gap-1">
                      <span className={clsx('tabular-nums text-[0.65rem]',
                        isAbove ? 'text-positive' : isBelow ? 'text-negative' : 'text-text-muted',
                      )}>
                        {entry.vwapDiffPct > 0 ? '+' : ''}{entry.vwapDiffPct.toFixed(2)}%
                      </span>
                      {entry.vwapPosition !== 'AT' && (
                        <span className={clsx(
                          'font-mono text-[0.48rem] px-1 py-px rounded-sm border',
                          isAbove
                            ? 'text-positive border-positive-dim bg-positive-bg'
                            : 'text-negative border-negative-dim bg-negative-bg',
                        )}>
                          {isAbove ? 'ABOVE' : 'BELOW'} VWAP
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <div className="flex items-center justify-center py-8">
            <span className="font-mono text-[0.65rem] text-text-muted">No prints matching filter</span>
          </div>
        )}
      </div>
    </div>
  )
}

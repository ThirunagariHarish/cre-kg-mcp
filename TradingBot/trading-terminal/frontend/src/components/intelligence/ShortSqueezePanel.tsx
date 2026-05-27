import React, { useState } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ────────────────────────────────────────────────────────────────────

export interface ShortSqueezeEntry {
  id: string
  ticker: string
  shortFloatPct: number
  borrowRate: number
  daysToCover: number
  shortInterest: number  // in millions of shares
  priceChangePct: number
  squeezeScore: number   // 0–100 composite
}

type SqueezeFilter = 'ALL' | 'HIGH' | 'EXTREME'

/**
 * Props for ShortSqueezePanel.
 * @prop entries - Short squeeze scanner entries.
 * @prop loading - Show skeleton loading state.
 */
export interface ShortSqueezePanelProps {
  entries?: ShortSqueezeEntry[]
  loading?: boolean
}

const SQUEEZE_CANDIDATES = ['GME', 'AMC', 'MSTR', 'CVNA', 'UPST', 'SOFI', 'RIVN', 'PLTR']

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtM(v: number): string {
  return `${v.toFixed(1)}M`
}

const SCORE_THRESHOLDS: Record<SqueezeFilter, number> = {
  ALL: 0,
  HIGH: 70,
  EXTREME: 90,
}

function SqueezeRiskBadge({ entry }: { entry: ShortSqueezeEntry }) {
  const isRisk = entry.shortFloatPct > 20 && entry.daysToCover > 5 && entry.priceChangePct > 5
  if (!isRisk) return null
  return (
    <span className="font-mono text-[0.48rem] px-1 py-px rounded-sm bg-[rgba(255,102,0,0.15)] text-accent-cyan border border-[rgba(255,102,0,0.3)] font-bold animate-pulse">
      SQUEEZE RISK
    </span>
  )
}

function ScoreBar({ score }: { score: number }) {
  const color =
    score >= 90 ? 'bg-negative' :
    score >= 70 ? 'bg-accent-cyan' :
    score >= 50 ? 'bg-warning' :
    'bg-positive'
  return (
    <div className="flex items-center gap-1">
      <div className="w-14 h-1.5 bg-bg-panel-raised overflow-hidden">
        <div className={clsx('h-full', color)} style={{ width: `${score}%` }} />
      </div>
      <span className={clsx(
        'font-mono text-[0.62rem] font-semibold tabular-nums w-8 text-right',
        score >= 90 ? 'text-negative' :
        score >= 70 ? 'text-accent-cyan' :
        score >= 50 ? 'text-warning' : 'text-positive',
      )}>
        {score}
      </span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ShortSqueezePanel({
  entries: propEntries,
  loading: propLoading = false,
}: ShortSqueezePanelProps) {
  const [filter, setFilter] = useState<SqueezeFilter>('ALL')
  const [sortField, setSortField] = useState<keyof ShortSqueezeEntry>('squeezeScore')

  const { data: shortData = [], isLoading: fetchLoading } = useQuery({
    queryKey: ['short-interest', SQUEEZE_CANDIDATES.join(',')],
    queryFn: async () => {
      const results = await Promise.allSettled(
        SQUEEZE_CANDIDATES.map(sym => apiGet<any>(API.shortInterest(sym)))
      )
      return results
        .filter((r): r is PromiseFulfilledResult<any> => r.status === 'fulfilled')
        .map(r => r.value)
        .filter(d => d.shortPercentOfFloat != null)
    },
    refetchInterval: 300_000,
    placeholderData: [],
  })
  const loading = propLoading || fetchLoading

  const liveEntries: ShortSqueezeEntry[] = shortData.map(d => ({
    id: d.symbol,
    ticker: d.symbol,
    shortFloatPct: (d.shortPercentOfFloat ?? 0) * 100,
    borrowRate: 0,
    daysToCover: d.shortRatio ?? 0,
    shortInterest: d.sharesShort != null ? d.sharesShort / 1_000_000 : 0,
    priceChangePct: 0,
    squeezeScore: Math.min(100, Math.round((d.shortPercentOfFloat ?? 0) * 200 + (d.shortRatio ?? 0) * 5)),
  }))

  const entries = propEntries ?? liveEntries

  const filtered = entries
    .filter(e => e.squeezeScore >= SCORE_THRESHOLDS[filter])
    .sort((a, b) => (b[sortField] as number) - (a[sortField] as number))

  const handleSort = (field: keyof ShortSqueezeEntry) => {
    setSortField(field)
  }

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header"><span>◈ Short Squeeze Scanner</span></div>
        <div className="p-2 space-y-1">
          {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-7 skeleton rounded-sm" />)}
        </div>
      </div>
    )
  }

  if (!entries.length) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="panel-header"><span className="flex-1">◈ Short Squeeze Scanner</span></div>
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
        <span className="flex-1">◈ Short Squeeze Scanner</span>
        <span className="font-mono text-[0.52rem] text-text-muted">{filtered.length} tickers</span>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-1 px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0">
        {(['ALL', 'HIGH', 'EXTREME'] as SqueezeFilter[]).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={clsx(
              'font-mono text-[0.58rem] px-2 py-0.5 rounded-sm border transition-colors',
              filter === f
                ? 'bg-[rgba(255,102,0,0.1)] text-accent-cyan border-accent-cyan'
                : 'text-text-muted border-border-muted hover:border-border-subtle',
            )}
          >
            {f === 'ALL' ? 'All' : f === 'HIGH' ? 'High Risk (>70)' : 'Extreme (>90)'}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <table className="data-table w-full">
          <thead>
            <tr>
              <th className="text-left pl-2.5">Ticker</th>
              <th
                className="cursor-pointer hover:text-accent-cyan"
                onClick={() => handleSort('shortFloatPct')}
              >
                Shrt Float%
              </th>
              <th
                className="cursor-pointer hover:text-accent-cyan"
                onClick={() => handleSort('borrowRate')}
              >
                Borrow%
              </th>
              <th
                className="cursor-pointer hover:text-accent-cyan"
                onClick={() => handleSort('daysToCover')}
              >
                DTC
              </th>
              <th>SI (M)</th>
              <th
                className="cursor-pointer hover:text-accent-cyan"
                onClick={() => handleSort('priceChangePct')}
              >
                Px Chg%
              </th>
              <th
                className="cursor-pointer hover:text-accent-cyan"
                onClick={() => handleSort('squeezeScore')}
              >
                Score
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(entry => {
              const highShort = entry.shortFloatPct > 20
              const highDTC = entry.daysToCover > 5
              const priceUp = entry.priceChangePct > 0
              return (
                <tr key={entry.id} className="hover:bg-bg-panel-hover transition-colors">
                  <td className="text-left pl-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-accent-cyan">{entry.ticker}</span>
                      <SqueezeRiskBadge entry={entry} />
                    </div>
                  </td>
                  <td className={clsx('tabular-nums', highShort ? 'text-accent-cyan font-semibold' : '')}>
                    {entry.shortFloatPct.toFixed(1)}%
                  </td>
                  <td className={clsx('tabular-nums', entry.borrowRate > 20 ? 'text-negative' : 'text-text-primary')}>
                    {entry.borrowRate.toFixed(1)}%
                  </td>
                  <td className={clsx('tabular-nums', highDTC ? 'text-warning font-semibold' : '')}>
                    {entry.daysToCover.toFixed(1)}
                  </td>
                  <td className="tabular-nums text-text-secondary">{fmtM(entry.shortInterest)}</td>
                  <td className={clsx('tabular-nums font-semibold', priceUp ? 'text-positive' : 'text-negative')}>
                    {priceUp ? '+' : ''}{entry.priceChangePct.toFixed(1)}%
                  </td>
                  <td>
                    <div className="flex justify-end">
                      <ScoreBar score={entry.squeezeScore} />
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <div className="flex items-center justify-center py-8">
            <span className="font-mono text-[0.65rem] text-text-muted">No entries matching filter</span>
          </div>
        )}
      </div>
    </div>
  )
}

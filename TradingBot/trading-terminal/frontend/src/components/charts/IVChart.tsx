/**
 * IVChart — Implied Volatility Rank gauge + term structure table.
 * Circular SVG gauge, 4-metric grid, term structure rows.
 */

import React, { useMemo } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface IVChartProps {
  symbol?: string
  ivRank?: number        // 0-100
  ivPercentile?: number  // 0-100
  currentIV?: number     // 0-1 (e.g. 0.28 = 28%)
  hv30?: number          // 0-1
  termStructure?: Record<string, number> // '7d', '14d', etc => IV 0-1
}

const TERM_KEYS = ['7d', '14d', '30d', '60d', '90d'] as const


// ── Gauge helpers ─────────────────────────────────────────────────────────────

/**
 * Returns SVG arc path for a circular gauge.
 * Starts from 7 o'clock (-210deg) sweeps clockwise to 5 o'clock (+30deg) = 240deg total.
 */
function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const toRad = (d: number) => (d * Math.PI) / 180
  const x1 = cx + r * Math.cos(toRad(startAngle))
  const y1 = cy + r * Math.sin(toRad(startAngle))
  const x2 = cx + r * Math.cos(toRad(endAngle))
  const y2 = cy + r * Math.sin(toRad(endAngle))
  const largeArc = endAngle - startAngle > 180 ? 1 : 0
  return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`
}

function gaugeColor(rank: number): string {
  if (rank < 30) return '#00e676'
  if (rank < 60) return '#ffcc00'
  return '#ff1744'
}

function ivLabel(rank: number): { label: string; color: string } {
  if (rank < 25) return { label: 'LOW', color: '#00e676' }
  if (rank < 50) return { label: 'MODERATE', color: '#ffcc00' }
  if (rank < 75) return { label: 'HIGH', color: '#ff9800' }
  return { label: 'EXTREME', color: '#ff1744' }
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface MetricBoxProps {
  label: string
  value: string
  color?: string
}

function MetricBox({ label, value, color = '#f0f0f0' }: MetricBoxProps) {
  return (
    <div className="flex flex-col items-center justify-center p-2 border border-border-subtle rounded-sm bg-bg-panel-raised">
      <span className="text-2xs font-mono text-text-muted uppercase tracking-wider">{label}</span>
      <span className="text-sm font-mono tabular-nums mt-0.5" style={{ color }}>{value}</span>
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IVChart({
  symbol = 'AAPL',
  ivRank,
  ivPercentile,
  currentIV,
  hv30,
  termStructure,
}: IVChartProps) {
  const { data: ivTermData = [] } = useQuery({
    queryKey: ['iv-term', symbol],
    queryFn: () => apiGet<Array<{ expiry: string; iv: number; strike: number }>>(API.optionsIvTerm(symbol)),
    enabled: !!symbol && !termStructure,
    refetchInterval: 300_000,
    staleTime: 240_000,
  })

  // Build termStructure map from IV term data — group by approximate DTE
  const derivedTermStructure: Record<string, number> | null = useMemo(() => {
    if (ivTermData.length === 0) return null
    const now = Date.now()
    const result: Record<string, number> = {}
    const buckets: Record<string, number[]> = { '7d': [], '14d': [], '30d': [], '60d': [], '90d': [] }
    ivTermData.forEach(item => {
      const daysToExp = Math.round((new Date(item.expiry).getTime() - now) / 86_400_000)
      if (daysToExp <= 10) buckets['7d'].push(item.iv)
      else if (daysToExp <= 21) buckets['14d'].push(item.iv)
      else if (daysToExp <= 45) buckets['30d'].push(item.iv)
      else if (daysToExp <= 75) buckets['60d'].push(item.iv)
      else buckets['90d'].push(item.iv)
    })
    for (const [key, vals] of Object.entries(buckets)) {
      if (vals.length > 0) {
        result[key] = vals.reduce((s, v) => s + v, 0) / vals.length
      }
    }
    return Object.keys(result).length > 0 ? result : null
  }, [ivTermData])

  const derivedCurrentIV = useMemo(() => {
    if (ivTermData.length === 0) return undefined
    const now = Date.now()
    const nearest = ivTermData
      .filter(i => new Date(i.expiry).getTime() > now)
      .sort((a, b) => new Date(a.expiry).getTime() - new Date(b.expiry).getTime())[0]
    return nearest?.iv
  }, [ivTermData])

  const rank = ivRank ?? 0
  const pct = ivPercentile ?? 0
  const iv = currentIV ?? derivedCurrentIV ?? 0
  const hv = hv30 ?? 0
  const term = termStructure ?? derivedTermStructure ?? {}

  const GAUGE_R = 52
  const CX = 70
  const CY = 70
  const GAP_ANGLE = 60 // degrees of empty arc at bottom
  const START_ANGLE = 90 + GAP_ANGLE / 2   // 120 degrees (below-left)
  const END_ANGLE = 90 - GAP_ANGLE / 2 + 360 // 420 -> effectively 420 mod 360 but we draw full arc

  // Track arc: 240 degree total
  const TRACK_START = 120  // degrees from 3 o'clock
  const TRACK_END = 420    // 120 + 300 = too much; use 120 + 240 = 360 for 240 deg
  const FILLED_END = TRACK_START + (rank / 100) * 240
  const color = gaugeColor(rank)
  const { label: rankLabel, color: labelColor } = ivLabel(rank)

  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`
  const fmtRank = (v: number) => v.toFixed(1)

  // Term structure: detect contango vs backwardation
  const termKeys = TERM_KEYS.filter(k => term[k] !== undefined)
  const maxTermIV = Math.max(...termKeys.map(k => term[k] ?? 0), 0.01)

  // Determine if term structure is backwardated (short term higher than long term)
  const firstTermIV = term[termKeys[0]] ?? 0
  const lastTermIV = term[termKeys[termKeys.length - 1]] ?? 0
  const isBackwardated = firstTermIV > lastTermIV

  return (
    <div className="flex flex-col h-full w-full bg-bg-panel overflow-hidden">
      {/* Panel header */}
      <div className="panel-header flex-shrink-0">
        <span className="text-accent-cyan">◈ IV Rank</span>
        <span className="text-text-secondary ml-2">{symbol}</span>
        <span className="ml-auto text-2xs" style={{ color: labelColor }}>{rankLabel}</span>
      </div>

      {/* Gauge + metrics */}
      <div className="flex-shrink-0 flex items-start gap-4 p-3">
        {/* SVG circular gauge */}
        <svg width="140" height="100" viewBox="0 0 140 100" className="flex-shrink-0">
          {/* Track background */}
          <path
            d={describeArc(CX, CY, GAUGE_R, TRACK_START, TRACK_START + 240)}
            fill="none"
            stroke="#1a1a1a"
            strokeWidth="8"
            strokeLinecap="round"
          />
          {/* Filled arc */}
          {rank > 0 && (
            <path
              d={describeArc(CX, CY, GAUGE_R, TRACK_START, FILLED_END)}
              fill="none"
              stroke={color}
              strokeWidth="8"
              strokeLinecap="round"
            />
          )}
          {/* Zone markers at 30% and 60% */}
          {[30, 60].map(threshold => {
            const angle = TRACK_START + (threshold / 100) * 240
            const RAD = (angle * Math.PI) / 180
            const innerR = GAUGE_R - 6
            const outerR = GAUGE_R + 2
            return (
              <line
                key={threshold}
                x1={CX + innerR * Math.cos(RAD)}
                y1={CY + innerR * Math.sin(RAD)}
                x2={CX + outerR * Math.cos(RAD)}
                y2={CY + outerR * Math.sin(RAD)}
                stroke="#333"
                strokeWidth="1.5"
              />
            )
          })}
          {/* Center text: rank value */}
          <text x={CX} y={CY - 8} textAnchor="middle" fill={color} fontSize="18" fontWeight="bold" fontFamily="IBM Plex Mono, monospace">
            {rank.toFixed(0)}
          </text>
          <text x={CX} y={CY + 8} textAnchor="middle" fill="#888" fontSize="9" fontFamily="IBM Plex Mono, monospace">
            IV RANK
          </text>
          {/* Zone labels */}
          <text x={CX - 42} y={CY + 40} textAnchor="start" fill="#00e676" fontSize="7" fontFamily="IBM Plex Mono, monospace">LOW</text>
          <text x={CX} y={CY + 48} textAnchor="middle" fill="#ffcc00" fontSize="7" fontFamily="IBM Plex Mono, monospace">MED</text>
          <text x={CX + 42} y={CY + 40} textAnchor="end" fill="#ff1744" fontSize="7" fontFamily="IBM Plex Mono, monospace">HIGH</text>
        </svg>

        {/* 4-metric grid */}
        <div className="flex-1 grid grid-cols-2 gap-1.5">
          <MetricBox label="IV%" value={fmtPct(iv)} color={color} />
          <MetricBox label="IV Rank" value={fmtRank(rank)} color={color} />
          <MetricBox label="IV Pct" value={`${fmtRank(pct)}%`} color={color} />
          <MetricBox label="HV30" value={fmtPct(hv)} color="#888" />
        </div>
      </div>

      <hr className="bb-divider" />

      {/* Term structure */}
      <div className="flex-1 overflow-auto min-h-0 p-2">
        <div className="text-2xs font-mono text-text-muted uppercase tracking-wider mb-1.5 px-1 flex items-center justify-between">
          <span>IV Term Structure</span>
          <span className={clsx('text-2xs', isBackwardated ? 'text-negative' : 'text-positive')}>
            {isBackwardated ? 'BACKWARDATED' : 'CONTANGO'}
          </span>
        </div>
        <table className="w-full font-mono text-xs border-collapse">
          <thead>
            <tr>
              {termKeys.map(k => (
                <th key={k} className="text-center text-text-muted text-2xs pb-1 border-b border-border-subtle uppercase">
                  {k}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              {termKeys.map(k => {
                const val = term[k] ?? 0
                const barHeight = Math.max(2, (val / maxTermIV) * 24)
                return (
                  <td key={k} className="text-center pt-1">
                    <div className="flex flex-col items-center gap-0.5">
                      {/* Mini bar */}
                      <div
                        className="w-4 rounded-sm"
                        style={{
                          height: `${barHeight}px`,
                          background: gaugeColor((val / maxTermIV) * 100),
                          opacity: 0.8,
                        }}
                      />
                      <span className={clsx('tabular-nums', ivColor(val))}>{fmtPct(val)}</span>
                    </div>
                  </td>
                )
              })}
            </tr>
          </tbody>
        </table>

        {/* IV vs HV comparison */}
        <div className="mt-2 p-2 border border-border-subtle rounded-sm bg-bg-panel-raised">
          <div className="text-2xs font-mono text-text-muted mb-1">IV / HV SPREAD</div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-bg-root rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(100, (iv / maxTermIV) * 100)}%`,
                  background: color,
                }}
              />
            </div>
            <span className={clsx('text-2xs tabular-nums font-mono', iv > hv ? 'text-negative' : 'text-positive')}>
              {iv > hv ? 'IV > HV' : 'IV < HV'}
            </span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="flex-shrink-0 px-3 py-1 border-t border-border-subtle text-2xs font-mono text-text-muted flex items-center">
        <span className="ml-auto" style={{ color: labelColor }}>{rankLabel} — IV RANK {rank.toFixed(1)}</span>
      </div>
    </div>
  )
}

// Helper (used internally in MetricBox)
function ivColor(iv: number): string {
  if (iv < 0.3) return 'text-positive'
  if (iv < 0.5) return 'text-warning'
  return 'text-negative'
}

export default IVChart

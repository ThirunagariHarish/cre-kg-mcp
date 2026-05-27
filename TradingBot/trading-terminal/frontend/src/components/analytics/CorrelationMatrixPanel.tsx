import React, { useState } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CorrelationMatrixPanelProps {
  symbols?: string[]
  correlations?: number[][]
  loading?: boolean
}


// ── Color Helpers ─────────────────────────────────────────────────────────────

/**
 * Maps correlation [-1, 1] → an RGB color string.
 * -1 → dark red, 0 → near-black, +1 → dark green
 */
function correlationToColor(value: number): string {
  if (value >= 0) {
    // 0 → #111, 1 → #004d22
    const t = value
    const r = Math.round(17 * (1 - t))
    const g = Math.round(17 + (230 - 17) * t * 0.42)
    const b = Math.round(17 * (1 - t))
    return `rgb(${r},${g},${b})`
  } else {
    // 0 → #111, -1 → #4d0010
    const t = Math.abs(value)
    const r = Math.round(17 + (255 - 17) * t * 0.42)
    const g = Math.round(17 * (1 - t))
    const b = Math.round(17 * (1 - t))
    return `rgb(${r},${g},${b})`
  }
}

function correlationLabel(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 0.9) return 'EXTREME'
  if (abs >= 0.8) return 'HIGH'
  if (abs >= 0.6) return 'MODERATE'
  if (abs >= 0.4) return 'LOW'
  return 'WEAK'
}

function textColorForCorrelation(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 0.85) return 'font-bold'
  return ''
}

// ── Legend Bar ────────────────────────────────────────────────────────────────

function LegendBar() {
  const stops = [
    { pos: 0, color: '#4d0010', label: '-1.0' },
    { pos: 50, color: '#111111', label: '0.0' },
    { pos: 100, color: '#004d22', label: '+1.0' },
  ]

  return (
    <div className="flex flex-col gap-0.5">
      <div
        className="h-2 w-full rounded-sm"
        style={{
          background:
            'linear-gradient(to right, #4d0010, #3d0010, #1a0008, #111111, #001a0a, #003018, #004d22)',
        }}
      />
      <div className="flex justify-between">
        {stops.map((s) => (
          <span key={s.pos} className="text-[0.5rem] font-mono text-text-muted">
            {s.label}
          </span>
        ))}
      </div>
    </div>
  )
}

// ── Tooltip State ─────────────────────────────────────────────────────────────

interface HoverCell {
  row: number
  col: number
  value: number
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function CorrelationMatrixPanel({
  symbols,
  correlations,
  loading = false,
}: CorrelationMatrixPanelProps) {
  const [hoverCell, setHoverCell] = useState<HoverCell | null>(null)

  const defaultSymbols = 'AAPL,NVDA,TSLA,META,SPY'
  const { data: corrData } = useQuery({
    queryKey: ['correlation', defaultSymbols],
    queryFn: () => apiGet<{ symbols: string[]; matrix: number[][] }>(`${API.marketCorrelation}?symbols=${defaultSymbols}&period=3mo`),
    refetchInterval: 300_000,
    staleTime: 240_000,
    enabled: !symbols && !correlations,
  })

  const syms = symbols ?? corrData?.symbols ?? []
  const corr = correlations ?? corrData?.matrix ?? []
  const n = syms.length

  // Detect high-correlation pairs (non-diagonal > 0.85)
  const highCorrPairs: Array<[string, string, number]> = []
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (corr[i] && corr[i][j] !== undefined && corr[i][j] > 0.85) {
        highCorrPairs.push([syms[i], syms[j], corr[i][j]])
      }
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ CORRELATION MATRIX</div>
        <div className="flex-1 skeleton m-2 rounded-sm" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
      {/* Header */}
      <div className="panel-header flex-shrink-0 flex items-center gap-2">
        <span>◈ CORRELATION MATRIX</span>
        {highCorrPairs.length > 0 && (
          <span className="ml-2 px-1.5 py-0.5 text-[0.5rem] font-mono border border-negative/60 text-negative bg-negative/10 tracking-widest animate-pulse-alert">
            ⚠ HIGH CORRELATION RISK
          </span>
        )}
        <span className="ml-auto text-[0.55rem] font-mono text-text-muted">
          {n}×{n}
        </span>
      </div>

      {/* Matrix */}
      <div className="flex-1 overflow-auto min-h-0 p-3">
        <div
          className="relative"
          style={{ display: 'grid', gridTemplateColumns: `60px repeat(${n}, 1fr)` }}
        >
          {/* Top-left corner */}
          <div className="h-7" />
          {/* Column headers */}
          {syms.map((sym) => (
            <div
              key={sym}
              className="h-7 flex items-center justify-center text-[0.6rem] font-mono text-accent-cyan tracking-widest"
            >
              {sym}
            </div>
          ))}

          {/* Rows */}
          {syms.map((rowSym, i) => (
            <React.Fragment key={rowSym}>
              {/* Row header */}
              <div className="h-10 flex items-center text-[0.6rem] font-mono text-accent-cyan tracking-widest pr-2 justify-end">
                {rowSym}
              </div>
              {/* Cells */}
              {syms.map((colSym, j) => {
                const val = corr[i]?.[j] ?? 0
                const bg = correlationToColor(val)
                const isDiag = i === j
                const isHovered = hoverCell?.row === i && hoverCell?.col === j
                return (
                  <div
                    key={colSym}
                    className={clsx(
                      'h-10 flex items-center justify-center cursor-default transition-all border',
                      isDiag ? 'border-accent-cyan/30' : 'border-transparent',
                      isHovered ? 'border-accent-cyan/60' : '',
                    )}
                    style={{ backgroundColor: bg }}
                    onMouseEnter={() => setHoverCell({ row: i, col: j, value: val })}
                    onMouseLeave={() => setHoverCell(null)}
                    role="gridcell"
                    aria-label={`${rowSym} × ${colSym}: ${val.toFixed(2)}`}
                  >
                    <span
                      className={clsx(
                        'text-[0.62rem] font-mono tabular-nums text-text-primary',
                        textColorForCorrelation(val),
                        isDiag && 'text-accent-cyan',
                      )}
                    >
                      {val.toFixed(2)}
                    </span>
                  </div>
                )
              })}
            </React.Fragment>
          ))}
        </div>

        {/* Tooltip */}
        {hoverCell !== null && !( hoverCell.row === hoverCell.col) && (
          <div className="mt-2 px-2 py-1.5 bg-bg-panel-raised border border-border-subtle font-mono text-[0.6rem]">
            <span className="text-accent-cyan">{syms[hoverCell.row]}</span>
            <span className="text-text-muted mx-1">×</span>
            <span className="text-accent-cyan">{syms[hoverCell.col]}</span>
            <span className="text-text-muted mx-2">:</span>
            <span
              className={clsx(
                'font-semibold',
                hoverCell.value >= 0 ? 'text-positive' : 'text-negative',
              )}
            >
              {hoverCell.value.toFixed(2)}
            </span>
            <span className="ml-2 text-text-muted">
              ({correlationLabel(hoverCell.value)})
            </span>
          </div>
        )}

        {/* High correlation warnings */}
        {highCorrPairs.length > 0 && (
          <div className="mt-2 space-y-0.5">
            {highCorrPairs.map(([a, b, v]) => (
              <div
                key={`${a}-${b}`}
                className="flex items-center gap-2 px-2 py-1 bg-negative/5 border border-negative/20"
              >
                <span className="text-[0.55rem] text-negative font-mono">⚠</span>
                <span className="text-[0.6rem] font-mono text-text-secondary">
                  <span className="text-accent-cyan">{a}</span> × <span className="text-accent-cyan">{b}</span>
                  {' '}correlation = <span className="text-negative font-semibold">{v.toFixed(2)}</span>
                  {' '}— consider reducing concentration
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Legend */}
        <div className="mt-3">
          <LegendBar />
        </div>
      </div>
    </div>
  )
}

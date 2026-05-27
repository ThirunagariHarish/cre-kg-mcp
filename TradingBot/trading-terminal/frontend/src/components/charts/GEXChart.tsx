/**
 * GEXChart — Gamma Exposure horizontal bar chart using native SVG.
 * Positive GEX = green (dealer long gamma, resistance)
 * Negative GEX = red (dealer short gamma, acceleration)
 */

import React from 'react'
import clsx from 'clsx'

// ── Types ─────────────────────────────────────────────────────────────────────

interface GEXBar {
  strike: number
  gex: number // in millions $
}

export interface GEXChartProps {
  symbol?: string
  currentPrice?: number
  data?: GEXBar[]
}


// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtGex = (v: number) => {
  const abs = Math.abs(v)
  if (abs >= 1000) return `${(v / 1000).toFixed(1)}B`
  return `${v.toFixed(0)}M`
}

// ── Component ─────────────────────────────────────────────────────────────────

export function GEXChart({ symbol = 'AAPL', currentPrice, data }: GEXChartProps) {
  if (!data) {
    return (
      <div className="flex flex-col h-full w-full bg-bg-panel overflow-hidden">
        <div className="panel-header flex-shrink-0">
          <span className="text-accent-cyan">◈ GEX / Gamma Exposure</span>
          <span className="text-text-secondary ml-2">{symbol}</span>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <div className="text-center font-mono text-[0.65rem] text-text-muted space-y-2">
            <div className="text-2xl opacity-20">⊘</div>
            <div>GEX data requires a premium options data feed (e.g., Unusual Whales)</div>
          </div>
        </div>
      </div>
    )
  }

  const bars = data
  const price = currentPrice ?? 0

  // Layout constants
  const ROW_H = 18
  const LEFT_PAD = 52  // strike label width
  const RIGHT_PAD = 48 // gex value label
  const BAR_AREA = 260 // total bar area width
  const ZERO_X = LEFT_PAD + BAR_AREA / 2

  const maxAbs = Math.max(...bars.map(b => Math.abs(b.gex)), 1)

  const sortedBars = [...bars].sort((a, b) => b.strike - a.strike)
  const svgH = sortedBars.length * ROW_H + 10
  const svgW = LEFT_PAD + BAR_AREA + RIGHT_PAD

  const maxPosBar = bars.reduce((m, b) => (b.gex > (m?.gex ?? -Infinity) ? b : m), bars[0])
  const minNegBar = bars.reduce((m, b) => (b.gex < (m?.gex ?? Infinity) ? b : m), bars[0])

  return (
    <div className="flex flex-col h-full w-full bg-bg-panel overflow-hidden">
      {/* Panel header */}
      <div className="panel-header flex-shrink-0">
        <span className="text-accent-cyan">◈ GEX / Gamma Exposure</span>
        <span className="text-text-secondary ml-2">{symbol}</span>
        <span className="text-text-muted ml-auto text-2xs">in $M</span>
      </div>

      {/* Legend row */}
      <div className="flex-shrink-0 flex items-center gap-4 px-3 py-1.5 border-b border-border-subtle text-2xs font-mono">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-sm bg-positive" />
          <span className="text-text-muted">LONG GAMMA (support)</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-sm bg-negative" />
          <span className="text-text-muted">SHORT GAMMA (accel)</span>
        </span>
        <span className="ml-auto text-text-muted">
          PRICE <span className="text-accent-cyan tabular-nums">{price.toFixed(2)}</span>
        </span>
      </div>

      {/* SVG bar chart */}
      <div className="flex-1 overflow-auto min-h-0 flex items-start justify-center p-2">
        <svg
          width={svgW}
          height={svgH}
          className="font-mono overflow-visible"
          style={{ fontSize: '9px' }}
        >
          {/* Column headers */}
          <text x={ZERO_X} y={8} textAnchor="middle" fill="#444" fontSize="8">0</text>

          {sortedBars.map((bar, i) => {
            const y = i * ROW_H + 12
            const barHalf = (Math.abs(bar.gex) / maxAbs) * (BAR_AREA / 2 - 4)
            const isPos = bar.gex >= 0
            const barX = isPos ? ZERO_X : ZERO_X - barHalf
            const barColor = isPos ? '#00e676' : '#ff1744'
            const barOpacity = 0.75

            // Strike matches current price row
            const isCurrentPrice = Math.abs(bar.strike - price) < 3
            // Highlight best positive / worst negative
            const isMaxPos = bar === maxPosBar && bar.gex > 0
            const isMinNeg = bar === minNegBar && bar.gex < 0

            return (
              <g key={bar.strike}>
                {/* Row highlight for current price */}
                {isCurrentPrice && (
                  <rect x={0} y={y - 1} width={svgW} height={ROW_H - 1} fill="rgba(255,102,0,0.07)" rx="1" />
                )}

                {/* Strike label */}
                <text
                  x={LEFT_PAD - 4}
                  y={y + ROW_H / 2 - 1}
                  textAnchor="end"
                  fill={isCurrentPrice ? '#ff6600' : isMaxPos || isMinNeg ? '#f0f0f0' : '#888'}
                  fontSize="9"
                  fontWeight={isCurrentPrice ? 'bold' : 'normal'}
                >
                  {bar.strike}
                </text>

                {/* Bar */}
                <rect
                  x={barX}
                  y={y + 2}
                  width={Math.max(barHalf, 1)}
                  height={ROW_H - 5}
                  fill={barColor}
                  opacity={barOpacity}
                  rx="1"
                />

                {/* GEX value label */}
                <text
                  x={LEFT_PAD + BAR_AREA + 4}
                  y={y + ROW_H / 2 - 1}
                  textAnchor="start"
                  fill={isPos ? '#00e676' : '#ff1744'}
                  fontSize="9"
                >
                  {fmtGex(bar.gex)}
                </text>

                {/* Max callout labels */}
                {isMaxPos && (
                  <text x={ZERO_X + barHalf + 2} y={y + 4} fill="#00e676" fontSize="7">▲ PEAK</text>
                )}
                {isMinNeg && (
                  <text x={ZERO_X - barHalf - 24} y={y + 4} fill="#ff1744" fontSize="7">▼ FLOOR</text>
                )}
              </g>
            )
          })}

          {/* Zero line */}
          <line
            x1={ZERO_X}
            y1={8}
            x2={ZERO_X}
            y2={svgH}
            stroke="#ff6600"
            strokeWidth="1"
            strokeDasharray="3 3"
            opacity="0.6"
          />

          {/* Current price horizontal line */}
          {(() => {
            const priceIdx = sortedBars.findIndex(b => Math.abs(b.strike - price) < 3)
            if (priceIdx === -1) return null
            const y = priceIdx * ROW_H + 12 + ROW_H / 2
            return (
              <line
                x1={LEFT_PAD}
                y1={y}
                x2={LEFT_PAD + BAR_AREA}
                y2={y}
                stroke="#ff6600"
                strokeWidth="1"
                opacity="0.5"
              />
            )
          })()}
        </svg>
      </div>

      {/* Footer summary */}
      <div className="flex-shrink-0 px-3 py-1 border-t border-border-subtle flex items-center gap-4 text-2xs font-mono text-text-muted">
        <span>+GEX PEAK <span className={clsx('tabular-nums', maxPosBar.gex > 0 ? 'text-positive' : 'text-text-secondary')}>{maxPosBar.strike}</span></span>
        <span className="text-border-subtle">|</span>
        <span>-GEX FLOOR <span className={clsx('tabular-nums', minNegBar.gex < 0 ? 'text-negative' : 'text-text-secondary')}>{minNegBar.strike}</span></span>
        <span className="ml-auto">NET GEX <span className={clsx('tabular-nums', bars.reduce((s, b) => s + b.gex, 0) >= 0 ? 'text-positive' : 'text-negative')}>
          {fmtGex(bars.reduce((s, b) => s + b.gex, 0))}
        </span></span>
      </div>
    </div>
  )
}

export default GEXChart

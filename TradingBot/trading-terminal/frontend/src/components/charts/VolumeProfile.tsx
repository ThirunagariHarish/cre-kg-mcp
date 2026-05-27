/**
 * VolumeProfile — Volume-at-price horizontal bars with VWAP, VAH, VAL, POC.
 * Native SVG bars, compact side-panel layout.
 */

import React, { useMemo } from 'react'
import clsx from 'clsx'

// ── Types ─────────────────────────────────────────────────────────────────────

interface VolumeLevel {
  price: number
  volume: number
  isValueArea?: boolean
}

export interface VolumeProfileProps {
  symbol?: string
  levels?: VolumeLevel[]
  vwap?: number
  vah?: number  // value area high
  val?: number  // value area low
  poc?: number  // point of control (max volume price)
}

// ── Mock generator ────────────────────────────────────────────────────────────

function generateVolumeProfile(basePrice = 185.5): {
  levels: VolumeLevel[]
  vwap: number
  vah: number
  val: number
  poc: number
} {
  const tickSize = 0.5
  const numLevels = 30
  const bottom = basePrice - numLevels * tickSize * 0.5
  const levels: Array<{ price: number; volume: number }> = []

  // Bell-curve-ish distribution centered near ATM
  for (let i = 0; i < numLevels; i++) {
    const px = parseFloat((bottom + i * tickSize).toFixed(2))
    const dist = Math.abs(i - numLevels * 0.55) / numLevels
    const vol = Math.round((1 - dist * 1.4) * 800_000 + Math.random() * 200_000)
    levels.push({ price: px, volume: Math.max(10_000, vol) })
  }

  // Sort descending by price (top of ladder = highest price)
  levels.sort((a, b) => b.price - a.price)

  const pocItem = levels.reduce((m, l) => (l.volume > m.volume ? l : m))
  const totalVol = levels.reduce((s, l) => s + l.volume, 0)

  // Value area: 70% of volume centered around POC
  const sortedByVol = [...levels].sort((a, b) => b.volume - a.volume)
  const vaTarget = totalVol * 0.7
  let vaVol = 0
  const vaSet = new Set<number>()
  for (const l of sortedByVol) {
    vaVol += l.volume
    vaSet.add(l.price)
    if (vaVol >= vaTarget) break
  }

  const vaPrices = Array.from(vaSet).sort((a, b) => a - b)
  const val = vaPrices[0] ?? pocItem.price
  const vah = vaPrices[vaPrices.length - 1] ?? pocItem.price

  const levelsWithVA = levels.map(l => ({ ...l, isValueArea: vaSet.has(l.price) }))

  // VWAP: sum(price*vol)/sum(vol)
  const vwap = levels.reduce((s, l) => s + l.price * l.volume, 0) / totalVol

  return { levels: levelsWithVA, vwap, vah, val, poc: pocItem.price }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtPx = (v: number) => v.toFixed(2)
const fmtVol = (v: number) => {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`
  return String(v)
}

// ── Component ─────────────────────────────────────────────────────────────────

export function VolumeProfile({ symbol = 'AAPL', levels, vwap, vah, val, poc }: VolumeProfileProps) {
  const mock = useMemo(() => generateVolumeProfile(), [])
  const activeLevels = levels ?? mock.levels
  const activeVwap = vwap ?? mock.vwap
  const activeVah = vah ?? mock.vah
  const activeVal = val ?? mock.val
  const activePoc = poc ?? mock.poc

  const maxVol = Math.max(...activeLevels.map(l => l.volume), 1)
  const BAR_MAX_W = 100  // px
  const ROW_H = 10
  const PRICE_W = 36
  const VOL_W = 38
  const TOTAL_W = PRICE_W + BAR_MAX_W + 6 + VOL_W
  const svgH = activeLevels.length * ROW_H + 4

  return (
    <div className="flex flex-col h-full w-full bg-bg-panel overflow-hidden">
      {/* Panel header */}
      <div className="panel-header flex-shrink-0">
        <span className="text-accent-cyan">◈ Volume Profile</span>
        {symbol && <span className="text-text-secondary ml-2">{symbol}</span>}
      </div>

      {/* Key levels row */}
      <div className="flex-shrink-0 grid grid-cols-2 gap-1 p-2 border-b border-border-subtle">
        <div className="flex flex-col items-center p-1.5 border border-border-subtle rounded-sm bg-bg-panel-raised">
          <span className="text-2xs font-mono text-accent-cyan uppercase tracking-wider">VWAP</span>
          <span className="text-sm font-mono tabular-nums text-accent-cyan font-bold">{fmtPx(activeVwap)}</span>
        </div>
        <div className="flex flex-col items-center p-1.5 border border-border-subtle rounded-sm bg-bg-panel-raised">
          <span className="text-2xs font-mono text-accent-cyan uppercase tracking-wider">POC</span>
          <span className="text-sm font-mono tabular-nums text-accent-cyan font-bold">{fmtPx(activePoc)}</span>
        </div>
        <div className="flex flex-col items-center p-1.5 border border-border-subtle rounded-sm bg-bg-panel-raised">
          <span className="text-2xs font-mono text-positive uppercase tracking-wider">VAH</span>
          <span className="text-xs font-mono tabular-nums text-positive">{fmtPx(activeVah)}</span>
        </div>
        <div className="flex flex-col items-center p-1.5 border border-border-subtle rounded-sm bg-bg-panel-raised">
          <span className="text-2xs font-mono text-negative uppercase tracking-wider">VAL</span>
          <span className="text-xs font-mono tabular-nums text-negative">{fmtPx(activeVal)}</span>
        </div>
      </div>

      {/* SVG volume bars */}
      <div className="flex-1 overflow-auto min-h-0">
        <svg
          width={TOTAL_W}
          height={svgH}
          className="font-mono"
          style={{ fontSize: '8px', display: 'block' }}
        >
          {activeLevels.map((level, i) => {
            const y = i * ROW_H
            const barW = (level.volume / maxVol) * BAR_MAX_W
            const isPoc = level.price === activePoc
            const isVwap = Math.abs(level.price - activeVwap) < 0.3
            const isVah = Math.abs(level.price - activeVah) < 0.01
            const isVal = Math.abs(level.price - activeVal) < 0.01
            const isVA = level.isValueArea

            const barColor = isPoc
              ? '#ff6600'
              : isVA
                ? 'rgba(0,188,212,0.5)'
                : 'rgba(100,100,100,0.4)'

            return (
              <g key={level.price}>
                {/* Row background highlight for key levels */}
                {(isPoc || isVwap) && (
                  <rect
                    x={0}
                    y={y}
                    width={TOTAL_W}
                    height={ROW_H - 1}
                    fill={isPoc ? 'rgba(255,102,0,0.08)' : 'rgba(0,188,212,0.06)'}
                  />
                )}

                {/* Price label */}
                <text
                  x={PRICE_W - 3}
                  y={y + ROW_H - 2}
                  textAnchor="end"
                  fill={isPoc ? '#ff6600' : isVah ? '#00e676' : isVal ? '#ff1744' : '#555'}
                  fontSize="8"
                >
                  {fmtPx(level.price)}
                </text>

                {/* Volume bar */}
                <rect
                  x={PRICE_W}
                  y={y + 1}
                  width={barW}
                  height={ROW_H - 2}
                  fill={barColor}
                  rx="0.5"
                />

                {/* Volume label */}
                <text
                  x={PRICE_W + BAR_MAX_W + 4}
                  y={y + ROW_H - 2}
                  textAnchor="start"
                  fill="#444"
                  fontSize="7"
                >
                  {fmtVol(level.volume)}
                </text>

                {/* VWAP line */}
                {isVwap && (
                  <line
                    x1={PRICE_W}
                    y1={y + ROW_H / 2}
                    x2={PRICE_W + BAR_MAX_W}
                    y2={y + ROW_H / 2}
                    stroke="#00bcd4"
                    strokeWidth="1"
                    strokeDasharray="2 2"
                  />
                )}

                {/* Side labels */}
                {isPoc && (
                  <text x={PRICE_W + barW + 2} y={y + ROW_H - 2} fill="#ff6600" fontSize="7">POC</text>
                )}
                {isVah && (
                  <text x={PRICE_W + barW + 2} y={y + ROW_H - 2} fill="#00e676" fontSize="7">VAH</text>
                )}
                {isVal && (
                  <text x={PRICE_W + barW + 2} y={y + ROW_H - 2} fill="#ff1744" fontSize="7">VAL</text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="flex-shrink-0 px-2 py-1.5 border-t border-border-subtle flex flex-wrap gap-2 text-2xs font-mono">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-accent-cyan opacity-50" />
          <span className="text-text-muted">VALUE AREA (70%)</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ background: '#ff6600' }} />
          <span className="text-text-muted">POC</span>
        </span>
      </div>
    </div>
  )
}

export default VolumeProfile

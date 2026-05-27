import React, { useRef, useState } from 'react'

/* ─────────────────────────────────────────────
   AgentPerformanceSparkline
   Mini 7-day P&L trend sparkline, SVG-based
───────────────────────────────────────────── */

interface AgentPerformanceSparklineProps {
  /** Array of daily P&L values (7 points for 7-day trend) */
  data: number[]
  /** SVG width in px. Default: 60 */
  width?: number
  /** SVG height in px. Default: 20 */
  height?: number
}

export default function AgentPerformanceSparkline({
  data,
  width = 60,
  height = 20,
}: AgentPerformanceSparklineProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [tooltip, setTooltip] = useState<{ x: number; y: number; value: number; index: number } | null>(null)

  if (!data || data.length < 2) {
    return (
      <svg width={width} height={height} className="block">
        <line x1={0} y1={height / 2} x2={width} y2={height / 2} stroke="#1e1e1e" strokeWidth={1} />
      </svg>
    )
  }

  const pad = 2
  const innerW = width - pad * 2
  const innerH = height - pad * 2

  const minVal = Math.min(...data)
  const maxVal = Math.max(...data)
  const range = maxVal - minVal || 1

  // Y: higher value = lower y (SVG top=0)
  const toX = (i: number) => pad + (i / (data.length - 1)) * innerW
  const toY = (v: number) => pad + (1 - (v - minVal) / range) * innerH

  const points = data.map((v, i) => ({ x: toX(i), y: toY(v) }))

  // Trend: last vs first
  const firstVal = data[0]
  const lastVal = data[data.length - 1]
  const isPositive = lastVal >= firstVal

  const lineColor = isPositive ? '#00e676' : '#ff1744'
  const dotColor = isPositive ? '#00e676' : '#ff1744'

  // Build polyline path
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')

  // Build fill area path (close under the line)
  const fillD =
    pathD +
    ` L ${points[points.length - 1].x.toFixed(1)} ${(pad + innerH).toFixed(1)}` +
    ` L ${points[0].x.toFixed(1)} ${(pad + innerH).toFixed(1)} Z`

  const lastPoint = points[points.length - 1]

  const formatPnl = (v: number) => {
    const sign = v >= 0 ? '+' : '-'
    const abs = Math.abs(v)
    if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`
    return `${sign}$${abs.toFixed(0)}`
  }

  const DAYS = ['D-6', 'D-5', 'D-4', 'D-3', 'D-2', 'D-1', 'Today']
  const dayLabel = (i: number) => DAYS[Math.max(0, DAYS.length - data.length + i)] ?? `D-${data.length - 1 - i}`

  return (
    <div className="relative inline-block" style={{ width, height }}>
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="block cursor-crosshair"
        onMouseMove={e => {
          const rect = svgRef.current?.getBoundingClientRect()
          if (!rect) return
          const mx = e.clientX - rect.left
          // Find closest data point
          let closest = 0
          let minDist = Infinity
          points.forEach((p, i) => {
            const dist = Math.abs(p.x - mx)
            if (dist < minDist) { minDist = dist; closest = i }
          })
          setTooltip({ x: points[closest].x, y: points[closest].y, value: data[closest], index: closest })
        }}
        onMouseLeave={() => setTooltip(null)}
      >
        {/* Fill */}
        <path
          d={fillD}
          fill={isPositive ? 'rgba(0,230,118,0.06)' : 'rgba(255,23,68,0.06)'}
        />
        {/* Line */}
        <path
          d={pathD}
          fill="none"
          stroke={lineColor}
          strokeWidth={1.2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {/* Hover highlight dot */}
        {tooltip && (
          <circle
            cx={tooltip.x}
            cy={tooltip.y}
            r={2.5}
            fill={isPositive ? '#00e676' : '#ff1744'}
            stroke="#000"
            strokeWidth={0.5}
          />
        )}
        {/* Last point dot (always shown) */}
        {!tooltip && (
          <circle
            cx={lastPoint.x}
            cy={lastPoint.y}
            r={2}
            fill={dotColor}
            stroke="#000000"
            strokeWidth={0.5}
          />
        )}
      </svg>
      {/* Tooltip */}
      {tooltip && (
        <div
          className="absolute z-50 pointer-events-none"
          style={{
            bottom: height + 4,
            left: Math.min(Math.max(tooltip.x - 28, 0), width - 56),
          }}
        >
          <div className="bg-bg-panel-raised border border-border-subtle px-1.5 py-0.5 rounded-sm shadow-panel whitespace-nowrap">
            <div className="font-mono text-[0.5rem] text-text-muted">{dayLabel(tooltip.index)}</div>
            <div
              className="font-mono text-[0.58rem] font-semibold tabular-nums"
              style={{ color: tooltip.value >= 0 ? '#00e676' : '#ff1744' }}
            >
              {formatPnl(tooltip.value)}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

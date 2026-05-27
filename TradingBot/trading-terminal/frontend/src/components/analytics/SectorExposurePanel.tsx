import React, { useState, useMemo } from 'react'
import clsx from 'clsx'
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SectorRow {
  name: string
  percent: number
  pnl: number
  color: string
}

export interface SectorExposurePanelProps {
  sectors?: SectorRow[]
  totalValue?: number
  loading?: boolean
}


// ── Custom Tooltip ────────────────────────────────────────────────────────────

interface TooltipProps {
  active?: boolean
  payload?: Array<{ name: string; value: number; payload: SectorRow }>
}

function SectorTooltip({ active, payload }: TooltipProps) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="bg-bg-panel border border-border-subtle px-2 py-1.5 font-mono text-[0.6rem] shadow-panel">
      <div className="text-text-primary font-semibold mb-0.5">{row.name}</div>
      <div className="text-text-secondary">{row.percent}% allocation</div>
      <div className={clsx(row.pnl >= 0 ? 'text-positive' : 'text-negative')}>
        {row.pnl >= 0 ? '+' : ''}${Math.abs(row.pnl).toLocaleString()} P&L
      </div>
    </div>
  )
}


// ── Bar ───────────────────────────────────────────────────────────────────────

interface AllocationBarProps {
  percent: number
  color: string
}

function AllocationBar({ percent, color }: AllocationBarProps) {
  return (
    <div className="h-1 w-full bg-bg-panel-raised rounded-sm overflow-hidden">
      <div
        className="h-full rounded-sm transition-all duration-300"
        style={{ width: `${percent}%`, backgroundColor: color, opacity: 0.7 }}
      />
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function SectorExposurePanel({
  sectors,
  totalValue,
  loading = false,
}: SectorExposurePanelProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null)

  const { data: positions = [] } = useQuery({
    queryKey: ['positions-for-sectors'],
    queryFn: () => apiGet<any[]>(API.portfolioPositions),
    refetchInterval: 30_000,
    placeholderData: [],
  })

  const { data: summary } = useQuery({
    queryKey: ['portfolio-summary-sector'],
    queryFn: () => apiGet<any>(API.portfolioSummary),
    refetchInterval: 30_000,
  })

  const SECTOR_COLORS: Record<string, string> = {
    'Technology': '#38bdf8', 'ETFs': '#a78bfa', 'Financials': '#f59e0b',
    'Healthcare': '#34d399', 'Energy': '#f87171', 'Consumer': '#fb923c',
    'Industrials': '#a3e635', 'Other': '#94a3b8', 'default': '#64748b',
  }
  const totalVal = summary?.total_value ?? 0
  const sectorMap: Record<string, { pnl: number; value: number }> = {}
  positions.forEach((p: any) => {
    const s = p.sector ?? p.industry ?? 'Other'
    if (!sectorMap[s]) sectorMap[s] = { pnl: 0, value: 0 }
    sectorMap[s].pnl += p.unrealized_pnl ?? 0
    sectorMap[s].value += p.market_value ?? 0
  })
  const derivedSectors: SectorRow[] = Object.entries(sectorMap).map(([name, d]) => ({
    name,
    percent: totalVal > 0 ? Math.round((d.value / totalVal) * 100) : 0,
    pnl: Math.round(d.pnl),
    color: SECTOR_COLORS[name] ?? SECTOR_COLORS['default'],
  }))

  const rows = sectors ?? (derivedSectors.length > 0 ? derivedSectors : [])
  const total = totalValue ?? totalVal

  const maxConcentration = Math.max(...rows.map((r) => r.percent))
  const overConcentrated = rows.filter((r) => r.percent > 30)

  if (loading) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ SECTOR EXPOSURE</div>
        <div className="flex-1 skeleton m-2 rounded-sm" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
      {/* Header */}
      <div className="panel-header flex-shrink-0">
        <span>◈ SECTOR EXPOSURE</span>
        {maxConcentration > 30 && (
          <span className="ml-2 px-1.5 py-0.5 text-[0.5rem] font-mono border border-warning/60 text-warning bg-warning/10 tracking-widest">
            ⚠ CONCENTRATION
          </span>
        )}
        <span className="ml-auto text-[0.55rem] font-mono text-text-muted tabular-nums">
          ${total.toLocaleString()}
        </span>
      </div>

      {/* Donut Chart */}
      <div className="relative flex-shrink-0" style={{ height: 180 }}>
        {/* Center overlay label */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10">
          <span className="text-[0.5rem] font-mono tracking-widest text-text-muted uppercase">Portfolio</span>
          <span className="text-sm font-mono font-semibold text-text-primary tabular-nums">
            ${(total / 1000).toFixed(0)}k
          </span>
        </div>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={rows}
              cx="50%"
              cy="50%"
              innerRadius={52}
              outerRadius={72}
              dataKey="percent"
              nameKey="name"
              paddingAngle={2}
              onMouseEnter={(_, index) => setActiveIndex(index)}
              onMouseLeave={() => setActiveIndex(null)}
              stroke="none"
            >
              {rows.map((row, index) => (
                <Cell
                  key={row.name}
                  fill={row.color}
                  opacity={activeIndex === null || activeIndex === index ? 0.85 : 0.35}
                  style={{ cursor: 'pointer', outline: 'none' }}
                />
              ))}
            </Pie>
            <Tooltip content={<SectorTooltip />} />
          </PieChart>
        </ResponsiveContainer>
      </div>


      {/* Legend Table */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {/* Header */}
        <div className="flex items-center gap-1 px-2 py-1 border-b border-border-subtle bg-bg-panel-raised sticky top-0">
          <span className="flex-1 text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">Sector</span>
          <span className="w-10 text-right text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">Alloc</span>
          <span className="w-16 text-right text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">P&L</span>
        </div>

        {rows.map((row, i) => (
          <div
            key={row.name}
            className={clsx(
              'px-2 py-1.5 border-b border-border-muted hover:bg-bg-panel-hover transition-colors cursor-default',
              activeIndex === i && 'bg-bg-panel-hover',
            )}
            onMouseEnter={() => setActiveIndex(i)}
            onMouseLeave={() => setActiveIndex(null)}
          >
            <div className="flex items-center gap-2 mb-1">
              {/* Color dot */}
              <div
                className="w-2 h-2 rounded-sm flex-shrink-0"
                style={{ backgroundColor: row.color, opacity: 0.85 }}
              />
              <span className="flex-1 text-[0.65rem] font-mono text-text-primary truncate">{row.name}</span>
              <span className="w-10 text-right text-[0.65rem] font-mono tabular-nums text-text-primary">
                {row.percent}%
              </span>
              <span
                className={clsx(
                  'w-16 text-right text-[0.65rem] font-mono tabular-nums',
                  row.pnl >= 0 ? 'text-positive' : 'text-negative',
                )}
              >
                {row.pnl >= 0 ? '+' : ''}${Math.abs(row.pnl).toLocaleString()}
              </span>
            </div>
            <AllocationBar percent={row.percent} color={row.color} />
          </div>
        ))}

        {/* Warnings */}
        {overConcentrated.length > 0 && (
          <div className="p-2 space-y-0.5">
            {overConcentrated.map((r) => (
              <div
                key={r.name}
                className="flex items-center gap-2 px-2 py-1 bg-warning/5 border border-warning/20"
              >
                <span className="text-[0.55rem] text-warning font-mono">⚠</span>
                <span className="text-[0.6rem] font-mono text-text-secondary">
                  <span className="text-text-primary">{r.name}</span> exceeds 30% concentration limit
                  {' '}({r.percent}%)
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

import React, { useMemo, useState } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Line,
  ComposedChart,
} from 'recharts'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface EquityCurvePanelProps {
  data?: Array<{ timestamp: number; cumulativePnl: number; dayPnl: number }>
  loading?: boolean
  period?: '1D' | '1W' | '1M' | '3M' | 'ALL'
  onPeriodChange?: (p: string) => void
}

interface DataPoint {
  timestamp: number
  cumulativePnl: number
  dayPnl: number
  benchmarkPnl?: number
}

// ── API response shape from GET /api/portfolio/equity-curve ──────────────────

interface EquityCurvePoint {
  timestamp: number
  nav: number
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

interface TooltipPayloadItem {
  name: string
  value: number
  color: string
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: number
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null
  const cumPnl = payload.find((p) => p.name === 'cumulativePnl')?.value ?? 0
  const dayPnl = payload.find((p) => p.name === 'dayPnl')?.value ?? 0
  const date = label ? new Date(label).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : ''

  return (
    <div className="bg-bg-panel border border-border-subtle px-2 py-1.5 font-mono text-[0.6rem] shadow-panel">
      <div className="text-text-muted mb-1">{date}</div>
      <div className={clsx('flex justify-between gap-4', cumPnl >= 0 ? 'text-positive' : 'text-negative')}>
        <span>CUMULATIVE</span>
        <span className="font-semibold">{cumPnl >= 0 ? '+' : ''}{cumPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}</span>
      </div>
      <div className={clsx('flex justify-between gap-4', dayPnl >= 0 ? 'text-positive' : 'text-negative')}>
        <span>DAY P&L</span>
        <span>{dayPnl >= 0 ? '+' : ''}{dayPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}</span>
      </div>
    </div>
  )
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string
  value: string
  color?: string
}

function StatCard({ label, value, color = 'text-text-primary' }: StatCardProps) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-1.5 border border-border-subtle bg-bg-panel-raised">
      <span className="text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">{label}</span>
      <span className={clsx('text-base font-mono font-semibold tabular-nums', color)}>{value}</span>
    </div>
  )
}

// ── Utils ─────────────────────────────────────────────────────────────────────

function filterByPeriod(data: DataPoint[], period: string): DataPoint[] {
  if (!data.length) return data
  const last = data[data.length - 1].timestamp
  const msPerDay = 86400000
  const cutoffs: Record<string, number> = {
    '1D': last - msPerDay,
    '1W': last - 7 * msPerDay,
    '1M': last - 30 * msPerDay,
    '3M': last - 90 * msPerDay,
    'ALL': 0,
  }
  const cutoff = cutoffs[period] ?? 0
  return data.filter((d) => d.timestamp >= cutoff)
}

function computeStats(data: DataPoint[]) {
  if (!data.length) return { totalReturn: 0, sharpe: 0, maxDrawdown: 0, winRate: 0 }

  const first = data[0].cumulativePnl
  const last = data[data.length - 1].cumulativePnl
  const totalReturn = first !== 0 ? ((last - first) / Math.abs(first)) * 100 : last > 0 ? 100 : 0

  const dailyReturns = data.map((d) => d.dayPnl)
  const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length
  const variance = dailyReturns.reduce((a, b) => a + (b - mean) ** 2, 0) / dailyReturns.length
  const std = Math.sqrt(variance)
  const sharpe = std > 0 ? (mean / std) * Math.sqrt(252) : 0

  let peak = -Infinity
  let maxDD = 0
  for (const d of data) {
    if (d.cumulativePnl > peak) peak = d.cumulativePnl
    const dd = peak > 0 ? ((d.cumulativePnl - peak) / peak) * 100 : 0
    if (dd < maxDD) maxDD = dd
  }

  const wins = dailyReturns.filter((r) => r > 0).length
  const winRate = dailyReturns.length > 0 ? (wins / dailyReturns.length) * 100 : 0

  return {
    totalReturn: Math.round(totalReturn * 10) / 10,
    sharpe: Math.round(sharpe * 100) / 100,
    maxDrawdown: Math.round(maxDD * 10) / 10,
    winRate: Math.round(winRate * 10) / 10,
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

const PERIODS = ['1D', '1W', '1M', '3M', 'ALL'] as const

export default function EquityCurvePanel({
  data,
  loading: loadingProp = false,
  period: periodProp,
  onPeriodChange,
}: EquityCurvePanelProps) {
  const [activePeriod, setActivePeriod] = useState<string>(periodProp ?? '1D')
  const [showBenchmark, setShowBenchmark] = useState(false)

  const { data: apiPoints, isLoading: apiLoading } = useQuery({
    queryKey: ['equity-curve', activePeriod],
    queryFn: () => apiGet<EquityCurvePoint[]>(API.equityCurve(activePeriod)),
    enabled: import.meta.env.VITE_MOCK_DATA !== 'true' && !data,
    staleTime: 30_000,
    retry: 1,
  })

  const loading = loadingProp || apiLoading

  // Convert API points (nav-based) into DataPoint format
  const convertedApiData = useMemo<DataPoint[]>(() => {
    if (!apiPoints?.length) return []
    const baseline = apiPoints[0].nav
    let prev = baseline
    return apiPoints.map(p => {
      const dayPnl = p.nav - prev
      prev = p.nav
      return {
        timestamp: p.timestamp,
        cumulativePnl: p.nav - baseline,
        dayPnl,
      }
    })
  }, [apiPoints])

  const allData = data ?? (convertedApiData.length > 0 ? convertedApiData : [])

  const filtered = useMemo(
    () => filterByPeriod(allData as DataPoint[], activePeriod),
    [allData, activePeriod],
  )

  const stats = useMemo(() => computeStats(filtered), [filtered])

  const lastCum = filtered.length ? filtered[filtered.length - 1].cumulativePnl : 0

  function handlePeriod(p: string) {
    setActivePeriod(p)
    onPeriodChange?.(p)
  }

  if (loading) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ EQUITY CURVE</div>
        <div className="flex-1 skeleton m-2 rounded-sm" />
      </div>
    )
  }

  if (!loading && filtered.length === 0) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ EQUITY CURVE</div>
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
    <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
      {/* Header */}
      <div className="panel-header flex-shrink-0">
        <span>◈ EQUITY CURVE</span>
        <span
          className={clsx(
            'ml-2 text-[0.6rem] font-mono tabular-nums',
            lastCum >= 0 ? 'text-positive' : 'text-negative',
          )}
        >
          {lastCum >= 0 ? '+' : ''}
          {lastCum.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {/* Period Selector */}
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => handlePeriod(p)}
              className={clsx(
                'px-1.5 py-0.5 text-[0.55rem] font-mono tracking-wider border transition-colors',
                activePeriod === p
                  ? 'border-accent-cyan text-accent-cyan bg-accent-cyan/10'
                  : 'border-border-subtle text-text-muted hover:text-text-secondary hover:border-border-active',
              )}
            >
              {p}
            </button>
          ))}
          {/* Benchmark Toggle */}
          <button
            onClick={() => setShowBenchmark((v) => !v)}
            className={clsx(
              'ml-2 px-1.5 py-0.5 text-[0.55rem] font-mono tracking-wider border transition-colors',
              showBenchmark
                ? 'border-warning text-warning bg-warning/10'
                : 'border-border-subtle text-text-muted hover:text-text-secondary',
            )}
          >
            SPY
          </button>
        </div>
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 px-1 pt-2">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={filtered} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <defs>
              <linearGradient id="ecGradientPos" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00e676" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#00e676" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="ecGradientNeg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#ff1744" stopOpacity={0.02} />
                <stop offset="95%" stopColor="#ff1744" stopOpacity={0.25} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="1 4"
              stroke="#1e1e1e"
              vertical={false}
            />
            <XAxis
              dataKey="timestamp"
              tickFormatter={(v: number) =>
                new Date(v).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
              }
              tick={{ fill: '#444444', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
              axisLine={{ stroke: '#1e1e1e' }}
              tickLine={false}
              minTickGap={40}
            />
            <YAxis
              tickFormatter={(v: number) =>
                v >= 0
                  ? `+$${(v / 1000).toFixed(0)}k`
                  : `-$${(Math.abs(v) / 1000).toFixed(0)}k`
              }
              tick={{ fill: '#444444', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip content={<CustomTooltip />} />
            {/* Zero line */}
            <ReferenceLine y={0} stroke="#ff6600" strokeDasharray="3 3" strokeWidth={1} />
            {/* Equity curve */}
            <Area
              type="monotone"
              dataKey="cumulativePnl"
              stroke={lastCum >= 0 ? '#00e676' : '#ff1744'}
              strokeWidth={1.5}
              fill={lastCum >= 0 ? 'url(#ecGradientPos)' : 'url(#ecGradientNeg)'}
              dot={false}
              activeDot={{ r: 3, fill: '#ff6600', strokeWidth: 0 }}
            />
            {/* Benchmark */}
            {showBenchmark && (
              <Line
                type="monotone"
                dataKey="benchmarkPnl"
                stroke="#ffcc00"
                strokeWidth={1}
                strokeDasharray="4 3"
                dot={false}
                activeDot={false}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Stats Row */}
      <div className="flex-shrink-0 grid grid-cols-4 gap-px border-t border-border-subtle bg-border-subtle mt-1">
        <StatCard
          label="Total Return"
          value={`${stats.totalReturn >= 0 ? '+' : ''}${stats.totalReturn}%`}
          color={stats.totalReturn >= 0 ? 'text-positive' : 'text-negative'}
        />
        <StatCard
          label="Sharpe Ratio"
          value={stats.sharpe.toFixed(2)}
          color={stats.sharpe >= 1 ? 'text-positive' : stats.sharpe >= 0 ? 'text-warning' : 'text-negative'}
        />
        <StatCard
          label="Max Drawdown"
          value={`${stats.maxDrawdown.toFixed(1)}%`}
          color="text-negative"
        />
        <StatCard
          label="Win Rate"
          value={`${stats.winRate.toFixed(1)}%`}
          color={stats.winRate >= 55 ? 'text-positive' : stats.winRate >= 45 ? 'text-warning' : 'text-negative'}
        />
      </div>
    </div>
  )
}

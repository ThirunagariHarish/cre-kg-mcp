import React, { useMemo, useState } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PerformanceMetrics {
  winRate: number         // 0-100
  profitFactor: number    // total gains / total losses
  sharpe: number
  sortino: number
  avgWin: number          // $ avg winning trade
  avgLoss: number         // $ avg losing trade (positive value)
  totalTrades: number
  avgHoldMinutes: number
  expectancy: number      // $ per trade
  totalWins: number
  totalLosses: number
}

export interface MetricsDashboardProps {
  metrics?: PerformanceMetrics
  loading?: boolean
}

type Period = 'TODAY' | '7D' | '30D' | 'ALL'

// ── Portfolio summary API shape ───────────────────────────────────────────────

interface PortfolioSummaryRaw {
  day_pnl?: number
  unrealized_pnl?: number
  total_value?: number
  position_count?: number
}

// ── Win Rate Mini Pie ─────────────────────────────────────────────────────────

function WinRatePie({ winRate }: { winRate: number }) {
  const data = [
    { value: winRate, color: '#00e676' },
    { value: 100 - winRate, color: '#1e1e1e' },
  ]
  return (
    <div className="w-10 h-10 flex-shrink-0">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={13}
            outerRadius={18}
            dataKey="value"
            paddingAngle={1}
            startAngle={90}
            endAngle={-270}
            stroke="none"
          >
            {data.map((d, i) => (
              <Cell key={i} fill={d.color} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Ratio Bar ─────────────────────────────────────────────────────────────────

interface RatioBarProps {
  winValue: number
  lossValue: number
}

function RatioBar({ winValue, lossValue }: RatioBarProps) {
  const total = winValue + lossValue
  const winPct = total > 0 ? (winValue / total) * 100 : 50
  return (
    <div className="flex h-1.5 w-full rounded-sm overflow-hidden gap-px">
      <div className="bg-positive/70 rounded-sm" style={{ width: `${winPct}%` }} />
      <div className="bg-negative/70 rounded-sm flex-1" />
    </div>
  )
}

// ── Metric Tile ───────────────────────────────────────────────────────────────

interface MetricTileProps {
  label: string
  value: string
  sublabel?: string
  color: string
  badge?: string
  badgeColor?: string
  children?: React.ReactNode
}

function MetricTile({ label, value, sublabel, color, badge, badgeColor, children }: MetricTileProps) {
  return (
    <div className="flex flex-col gap-1 p-2.5 border border-border-subtle bg-bg-panel-raised hover:bg-bg-panel-hover transition-colors">
      <div className="flex items-center justify-between">
        <span className="text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">{label}</span>
        {badge && (
          <span className={clsx('px-1 py-0 text-[0.5rem] border font-mono tracking-widest', badgeColor)}>
            {badge}
          </span>
        )}
      </div>
      <div className="flex items-end gap-2 justify-between">
        <span className={clsx('text-xl font-mono font-semibold tabular-nums leading-none', color)}>
          {value}
        </span>
        {children}
      </div>
      {sublabel && (
        <span className="text-[0.58rem] font-mono text-text-muted">{sublabel}</span>
      )}
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

const PERIODS: Period[] = ['TODAY', '7D', '30D', 'ALL']

export default function MetricsDashboard({
  metrics: metricsProp,
  loading: loadingProp = false,
}: MetricsDashboardProps) {
  const [period, setPeriod] = useState<Period>('TODAY')

  const { data: summaryRaw, isLoading: apiLoading } = useQuery({
    queryKey: ['portfolio-summary-metrics'],
    queryFn: () => apiGet<PortfolioSummaryRaw>(API.portfolioSummary),
    enabled: import.meta.env.VITE_MOCK_DATA !== 'true' && !metricsProp,
    staleTime: 30_000,
    retry: 1,
  })

  const loading = loadingProp || apiLoading

  // Derive minimal metrics from portfolio summary when available
  const derivedMetrics = useMemo<PerformanceMetrics | undefined>(() => {
    if (!summaryRaw) return undefined
    return {
      winRate: 0,
      profitFactor: 0,
      sharpe: 0,
      sortino: 0,
      avgWin: 0,
      avgLoss: 0,
      totalTrades: 0,
      avgHoldMinutes: 0,
      expectancy: 0,
      totalWins: 0,
      totalLosses: 0,
    }
  }, [summaryRaw])

  const metrics: PerformanceMetrics | undefined = useMemo(() => {
    return metricsProp ?? derivedMetrics
  }, [metricsProp, derivedMetrics])

  if (loading) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ PERFORMANCE METRICS</div>
        <div className="flex-1 skeleton m-2 rounded-sm" />
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ PERFORMANCE METRICS</div>
        <div className="flex items-center justify-center flex-1 text-text-muted font-mono text-[0.65rem]">
          <div className="text-center">
            <div className="text-text-dim mb-1">NO DATA</div>
            <div className="text-[0.55rem]">Pending backend integration</div>
          </div>
        </div>
      </div>
    )
  }

  const sharpeLabel = metrics.sharpe >= 2 ? 'EXCELLENT' : metrics.sharpe >= 1 ? 'GOOD' : metrics.sharpe >= 0.5 ? 'FAIR' : 'POOR'
  const sharpeColor =
    metrics.sharpe >= 2
      ? 'border-positive/60 text-positive'
      : metrics.sharpe >= 1
      ? 'border-warning/60 text-warning'
      : 'border-negative/60 text-negative'

  const wlRatio = metrics.avgLoss > 0 ? metrics.avgWin / metrics.avgLoss : 0

  return (
    <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
      {/* Header */}
      <div className="panel-header flex-shrink-0">
        <span>◈ PERFORMANCE METRICS</span>
        <div className="ml-auto flex items-center gap-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={clsx(
                'px-1.5 py-0.5 text-[0.55rem] font-mono tracking-wider border transition-colors',
                period === p
                  ? 'border-accent-cyan text-accent-cyan bg-accent-cyan/10'
                  : 'border-border-subtle text-text-muted hover:text-text-secondary hover:border-border-active',
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="flex-1 overflow-y-auto min-h-0 p-1">
        <div className="grid grid-cols-2 gap-px bg-border-subtle">
          {/* Win Rate */}
          <MetricTile
            label="Win Rate"
            value={`${metrics.winRate.toFixed(1)}%`}
            sublabel={`${metrics.totalWins}W / ${metrics.totalLosses}L`}
            color={metrics.winRate >= 60 ? 'text-positive' : metrics.winRate >= 50 ? 'text-warning' : 'text-negative'}
          >
            <WinRatePie winRate={metrics.winRate} />
          </MetricTile>

          {/* Profit Factor */}
          <MetricTile
            label="Profit Factor"
            value={metrics.profitFactor.toFixed(2)}
            sublabel="Total gains / losses"
            color={metrics.profitFactor >= 2 ? 'text-positive' : metrics.profitFactor >= 1.5 ? 'text-warning' : 'text-negative'}
            badge={metrics.profitFactor >= 2 ? 'STRONG' : metrics.profitFactor >= 1.2 ? 'OK' : 'WEAK'}
            badgeColor={
              metrics.profitFactor >= 2
                ? 'border-positive/60 text-positive'
                : metrics.profitFactor >= 1.2
                ? 'border-warning/60 text-warning'
                : 'border-negative/60 text-negative'
            }
          />

          {/* Sharpe */}
          <MetricTile
            label="Sharpe Ratio"
            value={metrics.sharpe.toFixed(2)}
            sublabel="Annualized risk-adj. return"
            color={metrics.sharpe >= 1 ? 'text-positive' : metrics.sharpe >= 0.5 ? 'text-warning' : 'text-negative'}
            badge={sharpeLabel}
            badgeColor={sharpeColor}
          />

          {/* Sortino */}
          <MetricTile
            label="Sortino Ratio"
            value={metrics.sortino.toFixed(2)}
            sublabel="Downside risk-adj. return"
            color={metrics.sortino >= 1.5 ? 'text-positive' : metrics.sortino >= 1 ? 'text-warning' : 'text-negative'}
          />

          {/* Avg Win vs Loss */}
          <MetricTile
            label="Avg Win / Avg Loss"
            value={`${wlRatio.toFixed(2)}x`}
            sublabel={`+$${metrics.avgWin} / -$${metrics.avgLoss}`}
            color={wlRatio >= 2 ? 'text-positive' : wlRatio >= 1.5 ? 'text-warning' : 'text-negative'}
          >
            <div className="w-16 flex flex-col gap-0.5">
              <RatioBar winValue={metrics.avgWin} lossValue={metrics.avgLoss} />
            </div>
          </MetricTile>

          {/* Total Trades */}
          <MetricTile
            label="Total Trades"
            value={metrics.totalTrades.toLocaleString()}
            sublabel={`${period} period`}
            color="text-text-primary"
          />

          {/* Avg Hold Time */}
          <MetricTile
            label="Avg Hold Time"
            value={
              metrics.avgHoldMinutes >= 60
                ? `${(metrics.avgHoldMinutes / 60).toFixed(1)}h`
                : `${metrics.avgHoldMinutes}m`
            }
            sublabel="Mean trade duration"
            color="text-text-secondary"
          />

          {/* Expectancy */}
          <MetricTile
            label="Expectancy"
            value={`$${metrics.expectancy}`}
            sublabel="Expected $ per trade"
            color={metrics.expectancy > 0 ? 'text-positive' : 'text-negative'}
          />
        </div>
      </div>
    </div>
  )
}

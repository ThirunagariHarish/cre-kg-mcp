import React, { useMemo } from 'react'
import clsx from 'clsx'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface DrawdownDataPoint {
  timestamp: number
  drawdownPct: number
}

export interface DrawdownPanelProps {
  data?: DrawdownDataPoint[]
  maxDrawdown?: number
  currentDrawdown?: number
  loading?: boolean
}


// ── High Watermark Lines ──────────────────────────────────────────────────────

function getHighWatermarkTimestamps(data: DrawdownDataPoint[]): number[] {
  const marks: number[] = []
  let lastWasAtZero = false
  for (const d of data) {
    if (d.drawdownPct === 0 || Math.abs(d.drawdownPct) < 0.01) {
      if (!lastWasAtZero) {
        marks.push(d.timestamp)
        lastWasAtZero = true
      }
    } else {
      lastWasAtZero = false
    }
  }
  return marks.slice(0, 8) // Cap to prevent overcrowding
}

// ── Custom Tooltip ────────────────────────────────────────────────────────────

interface TooltipPayloadItem {
  name: string
  value: number
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: number
}

function DrawdownTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null
  const dd = payload[0]?.value ?? 0
  const date = label
    ? new Date(label).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : ''
  return (
    <div className="bg-bg-panel border border-border-subtle px-2 py-1.5 font-mono text-[0.6rem] shadow-panel">
      <div className="text-text-muted mb-1">{date}</div>
      <div className={clsx('flex justify-between gap-4', dd < 0 ? 'text-negative' : 'text-positive')}>
        <span>DRAWDOWN</span>
        <span className="font-semibold">{dd.toFixed(2)}%</span>
      </div>
    </div>
  )
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string
  value: string
  subtext?: string
  color?: string
}

function StatCard({ label, value, subtext, color = 'text-text-primary' }: StatCardProps) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-1.5 border border-border-subtle bg-bg-panel-raised">
      <span className="text-[0.55rem] font-mono tracking-widest text-text-muted uppercase">{label}</span>
      <span className={clsx('text-base font-mono font-semibold tabular-nums', color)}>{value}</span>
      {subtext && <span className="text-[0.55rem] font-mono text-text-muted">{subtext}</span>}
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function DrawdownPanel({
  data,
  maxDrawdown: maxDdProp,
  currentDrawdown: curDdProp,
  loading = false,
}: DrawdownPanelProps) {
  const { data: equityCurve = [] } = useQuery({
    queryKey: ['equity-curve-drawdown', '3mo'],
    queryFn: () => apiGet<any[]>(API.equityCurve('3mo')),
    refetchInterval: 60_000,
    placeholderData: [],
  })

  const derivedData: DrawdownDataPoint[] = useMemo(() => {
    if (equityCurve.length < 2) return []
    let peak = equityCurve[0]?.value ?? 0
    return equityCurve.map((p: any) => {
      const val = p.value ?? p.equity ?? 0
      if (val > peak) peak = val
      const drawdown = peak > 0 ? ((val - peak) / peak) * 100 : 0
      return {
        timestamp: new Date(p.date ?? p.timestamp ?? Date.now()).getTime(),
        drawdownPct: Math.round(drawdown * 100) / 100,
      }
    })
  }, [equityCurve])

  const chartData = data ?? derivedData

  const maxDrawdown = useMemo(() => {
    if (maxDdProp !== undefined) return maxDdProp
    return Math.min(...chartData.map((d) => d.drawdownPct))
  }, [chartData, maxDdProp])

  const currentDrawdown = useMemo(() => {
    if (curDdProp !== undefined) return curDdProp
    return chartData.length ? chartData[chartData.length - 1].drawdownPct : 0
  }, [chartData, curDdProp])

  const hwTimestamps = useMemo(() => getHighWatermarkTimestamps(chartData), [chartData])

  // Avg drawdown duration: count consecutive negative streaks
  const avgDuration = useMemo(() => {
    let streakTotal = 0
    let streakCount = 0
    let currentStreak = 0
    for (const d of chartData) {
      if (d.drawdownPct < -0.1) {
        currentStreak++
      } else {
        if (currentStreak > 0) {
          streakTotal += currentStreak
          streakCount++
          currentStreak = 0
        }
      }
    }
    return streakCount > 0 ? Math.round(streakTotal / streakCount) : 0
  }, [chartData])

  // Recovery time: last streak length
  const recoveryDays = useMemo(() => {
    let streak = 0
    for (let i = chartData.length - 1; i >= 0; i--) {
      if ((chartData[i].drawdownPct ?? 0) < -0.1) streak++
      else break
    }
    return streak
  }, [chartData])

  const atHighWatermark = Math.abs(currentDrawdown) < 0.1

  if (loading) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ DRAWDOWN ANALYSIS</div>
        <div className="flex-1 skeleton m-2 rounded-sm" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
      {/* Header */}
      <div className="panel-header flex-shrink-0">
        <span>◈ DRAWDOWN ANALYSIS</span>
        {atHighWatermark && (
          <span className="ml-2 px-1.5 py-0.5 text-[0.5rem] font-mono border border-positive/60 text-positive bg-positive/10 tracking-widest">
            ◆ AT HIGH WATERMARK
          </span>
        )}
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 px-1 pt-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <defs>
              <linearGradient id="ddGradient" x1="0" y1="1" x2="0" y2="0">
                <stop offset="5%" stopColor="#ff1744" stopOpacity={0.35} />
                <stop offset="95%" stopColor="#ff1744" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="1 4" stroke="#1e1e1e" vertical={false} />
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
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              tick={{ fill: '#444444', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
              axisLine={false}
              tickLine={false}
              width={36}
              domain={[Math.min(maxDrawdown * 1.1, -0.5), 0.5]}
            />
            <Tooltip content={<DrawdownTooltip />} />
            {/* Zero line */}
            <ReferenceLine y={0} stroke="#ff6600" strokeWidth={1} />
            {/* High watermark recovery lines */}
            {hwTimestamps.map((ts) => (
              <ReferenceLine
                key={ts}
                x={ts}
                stroke="#00e676"
                strokeDasharray="2 4"
                strokeWidth={1}
                strokeOpacity={0.5}
              />
            ))}
            <Area
              type="monotone"
              dataKey="drawdownPct"
              stroke="#ff1744"
              strokeWidth={1.5}
              fill="url(#ddGradient)"
              dot={false}
              activeDot={{ r: 3, fill: '#ff6600', strokeWidth: 0 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Stats */}
      <div className="flex-shrink-0 grid grid-cols-4 gap-px border-t border-border-subtle bg-border-subtle mt-1">
        <StatCard
          label="Max Drawdown"
          value={`${maxDrawdown.toFixed(1)}%`}
          color="text-negative"
        />
        <StatCard
          label="Current DD"
          value={atHighWatermark ? '0.00%' : `${currentDrawdown.toFixed(2)}%`}
          color={atHighWatermark ? 'text-positive' : 'text-negative'}
          subtext={atHighWatermark ? 'High watermark' : undefined}
        />
        <StatCard
          label="Recovery Time"
          value={recoveryDays > 0 ? `${recoveryDays}d` : 'N/A'}
          color={recoveryDays > 0 ? 'text-warning' : 'text-text-muted'}
        />
        <StatCard
          label="Avg Duration"
          value={avgDuration > 0 ? `${avgDuration}d` : 'N/A'}
          color="text-text-secondary"
        />
      </div>
    </div>
  )
}

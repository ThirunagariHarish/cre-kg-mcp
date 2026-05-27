import React from 'react'
import clsx from 'clsx'
import {
  RadialBarChart,
  RadialBar,
  ResponsiveContainer,
  PolarAngleAxis,
} from 'recharts'

interface RiskGaugeProps {
  value: number    // 0-100
  label: string
  sublabel?: string
  max?: number
  size?: 'sm' | 'md' | 'lg'
}

function getGaugeColor(value: number): string {
  if (value >= 80) return '#ef4444'  // negative
  if (value >= 60) return '#f59e0b'  // warning
  return '#22c55e'                    // positive
}

export default function RiskGauge({
  value,
  label,
  sublabel,
  max = 100,
  size = 'sm',
}: RiskGaugeProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  const color = getGaugeColor(pct)

  const sizeConfig = {
    sm: { chartHeight: 70, textSize: 'text-lg', labelSize: 'text-[0.55rem]' },
    md: { chartHeight: 90, textSize: 'text-xl', labelSize: 'text-[0.6rem]' },
    lg: { chartHeight: 120, textSize: 'text-2xl', labelSize: 'text-xs' },
  }[size]

  const data = [{ value: pct, fill: color }]

  return (
    <div className="flex flex-col items-center gap-0.5">
      <div className="relative w-full" style={{ height: sizeConfig.chartHeight }}>
        <ResponsiveContainer width="100%" height={sizeConfig.chartHeight}>
          <RadialBarChart
            cx="50%"
            cy="85%"
            innerRadius="65%"
            outerRadius="100%"
            startAngle={180}
            endAngle={0}
            data={data}
          >
            <PolarAngleAxis
              type="number"
              domain={[0, 100]}
              angleAxisId={0}
              tick={false}
            />
            {/* Background track */}
            <RadialBar
              dataKey="value"
              cornerRadius={2}
              background={{ fill: '#263241' }}
              data={[{ value: 100 }]}
              isAnimationActive={false}
            />
            {/* Value bar */}
            <RadialBar
              dataKey="value"
              cornerRadius={2}
              isAnimationActive={false}
              data={data}
            />
          </RadialBarChart>
        </ResponsiveContainer>

        {/* Center text */}
        <div className="absolute inset-0 flex flex-col items-center justify-end pb-1">
          <span
            className={clsx(
              'font-mono font-semibold tabular-nums leading-none',
              sizeConfig.textSize
            )}
            style={{ color }}
          >
            {pct.toFixed(0)}%
          </span>
        </div>
      </div>

      {/* Labels */}
      <p className={clsx('font-mono font-medium uppercase tracking-wider text-text-secondary', sizeConfig.labelSize)}>
        {label}
      </p>
      {sublabel && (
        <p className={clsx('font-mono text-text-muted', sizeConfig.labelSize)}>
          {sublabel}
        </p>
      )}
    </div>
  )
}

import React from 'react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import clsx from 'clsx'

interface MiniChartProps {
  data: number[]
  color?: string
  width?: number
  height?: number
  className?: string
}

export default function MiniChart({
  data,
  color,
  width,
  height = 32,
  className,
}: MiniChartProps) {
  if (!data || data.length < 2) {
    return (
      <div
        className={clsx('flex items-end', className)}
        style={{ width: width ?? '100%', height }}
      >
        <div className="w-full h-px bg-border-subtle" />
      </div>
    )
  }

  const first = data[0]
  const last = data[data.length - 1]
  const isUp = last >= first
  const lineColor = color ?? (isUp ? '#22c55e' : '#ef4444')

  const chartData = data.map((v, i) => ({ v, i }))

  return (
    <div className={className} style={{ width: width ?? '100%', height }}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData}>
          <Line
            type="monotone"
            dataKey="v"
            stroke={lineColor}
            strokeWidth={1}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

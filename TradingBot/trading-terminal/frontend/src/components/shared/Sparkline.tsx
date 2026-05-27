import React from 'react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import clsx from 'clsx'

interface SparklineProps {
  data: number[]
  width?: number | string
  height?: number
  color?: string
  strokeWidth?: number
  className?: string
}

export default function Sparkline({
  data,
  width = '100%',
  height = 28,
  color,
  strokeWidth = 1,
  className,
}: SparklineProps) {
  if (!data || data.length < 2) {
    return (
      <div
        className={clsx('flex items-center', className)}
        style={{ width, height }}
      >
        <div className="w-full h-px bg-border-subtle" />
      </div>
    )
  }

  const first = data[0]
  const last = data[data.length - 1]
  const lineColor = color ?? (last >= first ? '#22c55e' : '#ef4444')
  const chartData = data.map((v, i) => ({ v, i }))

  return (
    <div className={className} style={{ width, height }}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
          <Line
            type="monotone"
            dataKey="v"
            stroke={lineColor}
            strokeWidth={strokeWidth}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

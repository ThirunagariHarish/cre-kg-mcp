import React from 'react'
import clsx from 'clsx'

type NumberFormat = 'currency' | 'percent' | 'compact' | 'bps' | 'decimal' | 'integer'

interface NumberDisplayProps {
  value: number
  format?: NumberFormat
  decimals?: number
  showDirection?: boolean
  showSign?: boolean
  className?: string
  prefix?: string
  suffix?: string
  colorize?: boolean
}

function formatValue(value: number, format: NumberFormat, decimals?: number): string {
  const d = decimals

  switch (format) {
    case 'currency': {
      const absVal = Math.abs(value)
      if (absVal >= 1_000_000_000)
        return `$${(value / 1_000_000_000).toFixed(d ?? 2)}B`
      if (absVal >= 1_000_000)
        return `$${(value / 1_000_000).toFixed(d ?? 2)}M`
      if (absVal >= 1_000)
        return `$${(value / 1_000).toFixed(d ?? 1)}K`
      return `$${value.toFixed(d ?? 2)}`
    }
    case 'percent':
      return `${value.toFixed(d ?? 2)}%`
    case 'compact': {
      const absVal = Math.abs(value)
      if (absVal >= 1_000_000_000)
        return `${(value / 1_000_000_000).toFixed(d ?? 1)}B`
      if (absVal >= 1_000_000)
        return `${(value / 1_000_000).toFixed(d ?? 1)}M`
      if (absVal >= 1_000)
        return `${(value / 1_000).toFixed(d ?? 1)}K`
      return value.toFixed(d ?? 0)
    }
    case 'bps':
      return `${value.toFixed(d ?? 1)} bps`
    case 'decimal':
      return value.toFixed(d ?? 4)
    case 'integer':
      return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
    default:
      return value.toFixed(d ?? 2)
  }
}

export default function NumberDisplay({
  value,
  format = 'decimal',
  decimals,
  showDirection = false,
  showSign = false,
  className,
  prefix,
  suffix,
  colorize = false,
}: NumberDisplayProps) {
  const isPositive = value > 0
  const isNegative = value < 0
  const isZero = value === 0

  const colorClass = colorize || showDirection
    ? isPositive ? 'text-positive' : isNegative ? 'text-negative' : 'text-text-secondary'
    : ''

  const formatted = formatValue(value, format, decimals)

  const sign = showSign && isPositive ? '+' : ''
  const arrow = showDirection
    ? isPositive ? '▲' : isNegative ? '▼' : '—'
    : ''

  return (
    <span
      className={clsx(
        'font-mono tabular-nums',
        colorClass,
        className
      )}
    >
      {showDirection && (
        <span className="mr-0.5 text-[0.7em]">{arrow}</span>
      )}
      {prefix}
      {sign}
      {formatted}
      {suffix}
    </span>
  )
}

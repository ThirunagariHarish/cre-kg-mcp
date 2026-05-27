import React, { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'

interface PriceCellProps {
  value: number
  previousValue?: number
  decimals?: number
  className?: string
  showSign?: boolean
}

type FlashDirection = 'up' | 'down' | null

export default function PriceCell({
  value,
  previousValue,
  decimals = 2,
  className,
  showSign = false,
}: PriceCellProps) {
  const [flash, setFlash] = useState<FlashDirection>(null)
  const prevRef = useRef<number | undefined>(previousValue)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    const prev = prevRef.current
    prevRef.current = value

    if (prev === undefined || prev === value) return

    // Trigger flash
    clearTimeout(timerRef.current)
    setFlash(value > prev ? 'up' : 'down')
    timerRef.current = setTimeout(() => setFlash(null), 700)
  }, [value])

  useEffect(() => {
    return () => clearTimeout(timerRef.current)
  }, [])

  const formatted = value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })

  return (
    <span
      className={clsx(
        'font-mono text-[0.7rem] tabular-nums transition-colors',
        'text-text-primary',
        flash === 'up' && 'price-flash-up',
        flash === 'down' && 'price-flash-down',
        className
      )}
    >
      {showSign && value > 0 ? '+' : ''}{formatted}
    </span>
  )
}

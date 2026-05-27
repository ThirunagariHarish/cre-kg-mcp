import React from 'react'
import clsx from 'clsx'
import { ArrowUpCircle, ArrowDownCircle, MinusCircle } from 'lucide-react'
import type { SignalDirection } from '@/types/signals'

interface SignalBadgeProps {
  direction: SignalDirection
  size?: 'sm' | 'md' | 'lg'
  showIcon?: boolean
  className?: string
}

const CONFIG: Record<SignalDirection, {
  label: string
  color: string
  icon: React.ReactNode
}> = {
  BUY: {
    label: 'BUY',
    color: 'text-positive border-positive-dim bg-positive-bg',
    icon: <ArrowUpCircle size={8} />,
  },
  SELL: {
    label: 'SELL',
    color: 'text-negative border-negative-dim bg-negative-bg',
    icon: <ArrowDownCircle size={8} />,
  },
  HOLD: {
    label: 'HOLD',
    color: 'text-warning border-warning-dim bg-warning-bg',
    icon: <MinusCircle size={8} />,
  },
  WATCH: {
    label: 'WATCH',
    color: 'text-accent-cyan border-accent-cyan-dim bg-info-bg',
    icon: <MinusCircle size={8} />,
  },
}

const SIZE_STYLES = {
  sm: 'text-[0.55rem] px-0.5 py-px gap-px',
  md: 'text-[0.6rem] px-1 py-px gap-0.5',
  lg: 'text-xs px-1.5 py-0.5 gap-1',
}

export default function SignalBadge({
  direction,
  size = 'md',
  showIcon = true,
  className,
}: SignalBadgeProps) {
  const conf = CONFIG[direction]

  return (
    <span
      className={clsx(
        'inline-flex items-center font-mono font-medium uppercase tracking-wider',
        'rounded-sm border',
        conf.color,
        SIZE_STYLES[size],
        className
      )}
    >
      {showIcon && conf.icon}
      {conf.label}
    </span>
  )
}

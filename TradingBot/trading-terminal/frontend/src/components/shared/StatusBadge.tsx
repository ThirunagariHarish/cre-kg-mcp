import React from 'react'
import clsx from 'clsx'

type StatusVariant = 'positive' | 'negative' | 'warning' | 'neutral' | 'info' | 'muted'

interface StatusBadgeProps {
  status: string
  variant: StatusVariant
  size?: 'xs' | 'sm' | 'md'
  dot?: boolean
  className?: string
}

const VARIANT_STYLES: Record<StatusVariant, string> = {
  positive: 'bg-positive-bg border-positive-dim text-positive',
  negative: 'bg-negative-bg border-negative-dim text-negative',
  warning: 'bg-warning-bg border-warning-dim text-warning',
  neutral: 'bg-bg-panel-raised border-border-subtle text-text-secondary',
  info: 'bg-info-bg border-info-dim text-accent-cyan',
  muted: 'bg-transparent border-border-muted text-text-muted',
}

const SIZE_STYLES = {
  xs: 'text-[0.55rem] px-0.5 py-px gap-px',
  sm: 'text-[0.6rem] px-1 py-px gap-0.5',
  md: 'text-xs px-1.5 py-0.5 gap-1',
}

const DOT_COLORS: Record<StatusVariant, string> = {
  positive: 'bg-positive',
  negative: 'bg-negative',
  warning: 'bg-warning',
  neutral: 'bg-text-muted',
  info: 'bg-accent-cyan',
  muted: 'bg-text-muted',
}

export default function StatusBadge({
  status,
  variant,
  size = 'sm',
  dot = false,
  className,
}: StatusBadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center font-mono font-medium uppercase tracking-wider rounded-sm border',
        VARIANT_STYLES[variant],
        SIZE_STYLES[size],
        className
      )}
    >
      {dot && (
        <span
          className={clsx(
            'rounded-full flex-shrink-0',
            size === 'xs' ? 'w-1 h-1' : size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2',
            DOT_COLORS[variant]
          )}
        />
      )}
      {status}
    </span>
  )
}

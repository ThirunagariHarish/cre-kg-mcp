import React, { useState } from 'react'
import clsx from 'clsx'
import { ChevronDown, ChevronRight, Minus } from 'lucide-react'

interface PanelAction {
  icon: React.ReactNode
  label: string
  onClick: () => void
}

interface PanelContainerProps {
  title: string
  badge?: number | string
  actions?: PanelAction[]
  children: React.ReactNode
  collapsible?: boolean
  defaultCollapsed?: boolean
  className?: string
  headerClassName?: string
  bodyClassName?: string
  active?: boolean
  mono?: boolean
}

export default function PanelContainer({
  title,
  badge,
  actions = [],
  children,
  collapsible = false,
  defaultCollapsed = false,
  className,
  headerClassName,
  bodyClassName,
  active = false,
  mono = false,
}: PanelContainerProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  const formattedBadge = badge !== undefined
    ? typeof badge === 'number' && badge > 99 ? '99+' : String(badge)
    : null

  return (
    <div
      className={clsx(
        'flex flex-col overflow-hidden',
        'border-b border-border-subtle',
        active && 'border-b-border-active',
        className
      )}
    >
      {/* ── Panel Header ── */}
      <div
        className={clsx(
          'flex items-center gap-1.5 px-2.5 py-1.5',
          'border-b border-border-subtle',
          'bg-bg-panel flex-shrink-0',
          active && 'border-b-border-active bg-bg-panel-raised',
          collapsible && 'cursor-pointer hover:bg-bg-panel-raised transition-colors',
          headerClassName
        )}
        onClick={collapsible ? () => setCollapsed(v => !v) : undefined}
        role={collapsible ? 'button' : undefined}
        aria-expanded={collapsible ? !collapsed : undefined}
      >
        {/* Collapse toggle */}
        {collapsible && (
          <span className="text-text-muted flex-shrink-0 w-3">
            {collapsed
              ? <ChevronRight size={10} className="text-text-muted" />
              : <ChevronDown size={10} className="text-text-muted" />
            }
          </span>
        )}

        {/* Active indicator bar */}
        {active && !collapsible && (
          <span className="w-0.5 h-3 bg-accent-cyan rounded-full flex-shrink-0" />
        )}

        {/* Title */}
        <span
          className={clsx(
            'flex-1 text-[0.6rem] font-medium uppercase tracking-widest',
            mono ? 'font-mono' : 'font-ui',
            active ? 'text-accent-cyan' : 'text-text-secondary',
            'truncate'
          )}
        >
          {title}
        </span>

        {/* Badge */}
        {formattedBadge && (
          <span
            className={clsx(
              'flex-shrink-0 font-mono text-[0.55rem] px-1 py-px rounded-sm border',
              active
                ? 'bg-info-bg text-accent-cyan border-accent-cyan-dim'
                : 'bg-bg-panel-raised text-text-muted border-border-muted'
            )}
          >
            {formattedBadge}
          </span>
        )}

        {/* Actions */}
        {actions.map((action, i) => (
          <button
            key={i}
            onClick={e => { e.stopPropagation(); action.onClick() }}
            title={action.label}
            aria-label={action.label}
            className={clsx(
              'flex-shrink-0 p-0.5 rounded-sm',
              'text-text-muted hover:text-text-primary',
              'hover:bg-bg-panel-raised',
              'transition-colors duration-100',
              'focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent-cyan'
            )}
          >
            {action.icon}
          </button>
        ))}

        {/* Collapse indicator (minimise dash if not collapsible-chevron) */}
        {!collapsible && (
          <span className="text-text-muted flex-shrink-0 opacity-0 group-hover:opacity-100">
            <Minus size={8} />
          </span>
        )}
      </div>

      {/* ── Panel Body ── */}
      {!collapsed && (
        <div
          className={clsx(
            'flex-1 overflow-auto min-h-0',
            bodyClassName
          )}
        >
          {children}
        </div>
      )}
    </div>
  )
}

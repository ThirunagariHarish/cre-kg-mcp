import React, { useEffect } from 'react'
import clsx from 'clsx'
import { X, AlertTriangle, CheckCircle2, Info, Zap, AlertOctagon } from 'lucide-react'
import { useTerminalStore } from '@/stores/terminalStore'
import type { Alert } from '@/stores/terminalStore'

const ALERT_CONFIG = {
  SIGNAL_HIGH_CONFIDENCE: {
    icon: <Zap size={11} />,
    color: 'border-accent-cyan text-accent-cyan bg-info-bg',
    title: 'HIGH CONFIDENCE SIGNAL',
  },
  RISK_BREACH: {
    icon: <AlertOctagon size={11} />,
    color: 'border-negative text-negative bg-negative-bg',
    title: 'RISK BREACH',
  },
  FILL_COMPLETE: {
    icon: <CheckCircle2 size={11} />,
    color: 'border-positive text-positive bg-positive-bg',
    title: 'ORDER FILLED',
  },
  ERROR: {
    icon: <AlertTriangle size={11} />,
    color: 'border-negative text-negative bg-negative-bg',
    title: 'ERROR',
  },
  INFO: {
    icon: <Info size={11} />,
    color: 'border-border-subtle text-text-secondary bg-bg-panel-raised',
    title: 'INFO',
  },
  WARNING: {
    icon: <AlertTriangle size={11} />,
    color: 'border-warning text-warning bg-warning-bg',
    title: 'WARNING',
  },
}

interface AlertItemProps {
  alert: Alert
  onDismiss: () => void
}

function AlertItem({ alert, onDismiss }: AlertItemProps) {
  const conf = ALERT_CONFIG[alert.type] ?? ALERT_CONFIG.INFO

  useEffect(() => {
    const timer = setTimeout(onDismiss, 10_000)
    return () => clearTimeout(timer)
  }, [onDismiss])

  return (
    <div
      className={clsx(
        'flex items-start gap-2 p-2.5 border rounded-sm',
        'w-72 shadow-dropdown',
        'animate-slide-in-right',
        conf.color
      )}
    >
      <span className="flex-shrink-0 mt-px">{conf.icon}</span>

      <div className="flex-1 min-w-0">
        <div className="font-mono text-[0.6rem] font-semibold uppercase tracking-widest mb-0.5">
          {conf.title}
        </div>
        <p className="font-mono text-[0.65rem] leading-relaxed opacity-90">
          {alert.message}
        </p>
        {alert.symbol && (
          <span className="font-mono text-[0.65rem] font-bold mt-0.5 block">
            {alert.symbol}
          </span>
        )}
      </div>

      <button
        onClick={onDismiss}
        className="flex-shrink-0 p-0.5 opacity-60 hover:opacity-100 transition-opacity"
        title="Dismiss"
      >
        <X size={9} />
      </button>
    </div>
  )
}

export default function AlertRail() {
  const alerts = useTerminalStore(s => s.alerts)
  const dismissAlert = useTerminalStore(s => s.dismissAlert)

  if (alerts.length === 0) return null

  // Show max 5 at a time
  const visible = alerts.slice(0, 5)

  return (
    <div
      className="fixed top-10 right-2 z-toast flex flex-col gap-1.5 pointer-events-none"
      aria-live="polite"
      aria-label="Notifications"
    >
      {visible.map(alert => (
        <div key={alert.id} className="pointer-events-auto">
          <AlertItem
            alert={alert}
            onDismiss={() => dismissAlert(alert.id)}
          />
        </div>
      ))}
      {alerts.length > 5 && (
        <div className="font-mono text-[0.55rem] text-text-muted text-right pr-1 pointer-events-auto">
          +{alerts.length - 5} more
        </div>
      )}
    </div>
  )
}

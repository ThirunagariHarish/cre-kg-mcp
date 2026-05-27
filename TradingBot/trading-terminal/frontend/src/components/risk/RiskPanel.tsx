import React from 'react'
import clsx from 'clsx'
import { Shield, ShieldAlert, ShieldOff, AlertTriangle } from 'lucide-react'
import type { RiskStatus, RiskBreach } from '@/types/risk'
import KillSwitchButton from './KillSwitchButton'

function fmt$(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000)     return `$${(v / 1_000).toFixed(1)}K`
  return `$${v.toFixed(2)}`
}

function MetricRow({ label, value, color = 'text-text-primary' }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-border-muted last:border-0">
      <span className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wide">{label}</span>
      <span className={clsx('font-mono text-[0.7rem] tabular-nums font-medium', color)}>{value}</span>
    </div>
  )
}

function GaugeBar({ value, label }: { value: number; label: string }) {
  const clamped = Math.min(100, Math.max(0, value))
  const barColor = clamped >= 80 ? 'bg-negative' : clamped >= 60 ? 'bg-warning' : 'bg-positive'
  const textColor = clamped >= 80 ? 'text-negative' : clamped >= 60 ? 'text-warning' : 'text-positive'
  return (
    <div className="flex-1">
      <div className="flex justify-between items-center mb-1">
        <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-wider">{label}</span>
        <span className={clsx('font-mono text-[0.68rem] tabular-nums font-semibold', textColor)}>
          {clamped.toFixed(1)}%
        </span>
      </div>
      <div className="h-1.5 bg-bg-panel-raised rounded-full overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all', barColor)}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  )
}

function BreachRow({ breach }: { breach: RiskBreach }) {
  const color = { INFO: 'text-accent-cyan', WARNING: 'text-warning', CRITICAL: 'text-negative' }[breach.severity]
  return (
    <div className="flex items-start gap-2 px-2.5 py-1.5 border-b border-border-muted bg-bg-panel-raised">
      <AlertTriangle size={9} className={clsx('flex-shrink-0 mt-px', color)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={clsx('font-mono text-[0.55rem] font-semibold uppercase', color)}>{breach.severity}</span>
          <span className="font-mono text-[0.55rem] text-text-muted">{breach.rule}</span>
        </div>
        <p className="font-mono text-[0.6rem] text-text-secondary leading-relaxed mt-px">{breach.message}</p>
      </div>
    </div>
  )
}

interface RiskPanelProps {
  riskStatus: RiskStatus
  onKillSwitch: () => void
  loading?: boolean
}

export default function RiskPanel({ riskStatus, onKillSwitch, loading = false }: RiskPanelProps) {
  const { metrics, policy, breaches, killSwitchActive } = riskStatus
  const criticals = breaches.filter(b => !b.resolved && b.severity === 'CRITICAL')
  const warnings  = breaches.filter(b => !b.resolved && b.severity === 'WARNING')
  const active    = breaches.filter(b => !b.resolved)

  if (loading) {
    return <div className="p-2 space-y-1.5">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-5 skeleton rounded-sm" />)}</div>
  }

  const statusColor = criticals.length > 0 ? 'text-negative' : warnings.length > 0 ? 'text-warning' : 'text-positive'
  const statusLabel = criticals.length > 0
    ? `${criticals.length} CRITICAL`
    : warnings.length > 0
      ? `${warnings.length} WARNING`
      : 'CLEAR'

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Panel Header */}
      <div className="panel-header">
        {criticals.length > 0
          ? <ShieldAlert size={10} className="text-negative flex-shrink-0" />
          : <Shield size={10} className={clsx('flex-shrink-0', warnings.length > 0 ? 'text-warning' : 'text-positive')} />
        }
        <span className="flex-1">◈ Risk Metrics</span>
        <span className={clsx('font-mono text-[0.6rem] font-semibold', statusColor)}>{statusLabel}</span>
      </div>

      {/* Kill Switch Active Banner */}
      {killSwitchActive && (
        <div className="flex items-center gap-2 px-2.5 py-2 bg-negative-bg border-b border-negative flex-shrink-0">
          <ShieldOff size={10} className="text-negative animate-pulse flex-shrink-0" />
          <span className="font-mono text-[0.62rem] text-negative font-semibold tracking-wider">
            KILL SWITCH ACTIVE — Trading Halted
          </span>
        </div>
      )}

      {/* Gauges */}
      <div className="flex gap-3 px-2.5 py-2.5 border-b border-border-subtle flex-shrink-0">
        <GaugeBar value={metrics.dailyLossUsedPercent} label="Daily Loss" />
        <GaugeBar value={metrics.totalExposurePercent} label="Exposure" />
      </div>

      {/* Key Metrics */}
      <div className="px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0">
        <MetricRow label="Total Exposure"  value={fmt$(metrics.totalExposure)} />
        <MetricRow label="Net Exposure"    value={fmt$(metrics.netExposure)} />
        <MetricRow
          label="Daily P&L"
          value={fmt$(metrics.dailyPnl)}
          color={metrics.dailyPnl >= 0 ? 'text-positive' : 'text-negative'}
        />
        <MetricRow
          label="Max Drawdown"
          value={`${metrics.maxDrawdownPercent.toFixed(2)}%`}
          color={metrics.maxDrawdownPercent > 10 ? 'text-negative' : metrics.maxDrawdownPercent > 5 ? 'text-warning' : 'text-text-primary'}
        />
        <MetricRow label="Open Positions" value={String(metrics.openPositionCount)} />
        {metrics.varDaily ? (
          <MetricRow label="Daily VaR" value={fmt$(metrics.varDaily)} color="text-warning" />
        ) : null}
      </div>

      {/* Policy Limits */}
      <div className="px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0">
        <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1">Policy Limits</p>
        {[
          { label: 'Max Position',      value: `${policy.maxPositionSizePercent}% / ${fmt$(policy.maxSinglePositionValue)}` },
          { label: 'Daily Loss Limit',  value: fmt$(policy.maxDailyLossAbsolute) },
          { label: 'Max Drawdown',      value: `${policy.maxDrawdownPercent}%` },
          { label: 'Max Order Value',   value: fmt$(policy.maxOrderValue) },
        ].map(({ label, value }) => (
          <div key={label} className="flex items-center justify-between py-0.5">
            <span className="font-mono text-[0.58rem] text-text-muted">{label}</span>
            <span className="font-mono text-[0.6rem] text-text-secondary tabular-nums">{value}</span>
          </div>
        ))}
      </div>

      {/* Active Breaches */}
      {active.length > 0 && (
        <div className="border-b border-border-subtle flex-shrink-0">
          <div className="px-2.5 py-1.5">
            <p className="font-mono text-[0.55rem] text-negative uppercase tracking-widest">
              Breaches ({active.length})
            </p>
          </div>
          {active.map(b => <BreachRow key={b.id} breach={b} />)}
        </div>
      )}

      {/* Kill Switch */}
      <div className="p-2.5 mt-auto">
        <KillSwitchButton onActivate={onKillSwitch} active={killSwitchActive} />
      </div>
    </div>
  )
}

import React, { useState, useCallback } from 'react'
import clsx from 'clsx'
import type { RiskPolicy, RiskMetrics } from '@/types/risk'

// ── Props ─────────────────────────────────────────────────────────────────────

interface RiskPolicyEditorProps {
  policy?: RiskPolicy
  currentMetrics?: RiskMetrics
  onSave?: (policy: RiskPolicy) => Promise<void>
}

// ── Defaults ──────────────────────────────────────────────────────────────────

const DEFAULT_POLICY: RiskPolicy = {
  id: 'default',
  name: 'Default Risk Policy',
  description: 'Standard trading risk limits',
  enabled: true,
  maxPositionSizePercent: 5,
  maxSinglePositionValue: 50000,
  maxPositionCount: 20,
  maxDailyLossPercent: 2,
  maxDailyLossAbsolute: 5000,
  maxDrawdownPercent: 10,
  maxOrderValue: 25000,
  maxOrderQuantity: 1000,
  maxSectorExposurePercent: 25,
  maxSymbolExposurePercent: 10,
  killSwitchEnabled: true,
  killSwitchDailyLossThreshold: 3000,
  updatedAt: Date.now(),
}

const DEFAULT_METRICS: RiskMetrics = {
  totalExposure: 45000,
  totalExposurePercent: 45,
  netExposure: 30000,
  longExposure: 40000,
  shortExposure: 10000,
  dailyPnl: -800,
  dailyPnlPercent: -0.8,
  dailyLossUsedPercent: 16,
  maxDrawdown: 2500,
  maxDrawdownPercent: 2.5,
  openPositionCount: 7,
  varDaily: 1200,
  sharpeRatio: 1.4,
  timestamp: Date.now(),
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(1)}K`
  return `$${v.toFixed(0)}`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionHeader({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-2 mt-3 mb-1.5">
      <span className="font-mono text-[0.55rem] text-accent-cyan uppercase tracking-widest">{title}</span>
      <div className="flex-1 h-px bg-border-subtle" />
    </div>
  )
}

interface PolicyFieldProps {
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  prefix?: string
  suffix?: string
  /** Current metric value (0–1 ratio of utilization) */
  utilizationRatio?: number
  formatValue?: (v: number) => string
}

function PolicyField({
  label,
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  prefix = '',
  suffix = '',
  utilizationRatio,
  formatValue,
}: PolicyFieldProps) {
  const pct = utilizationRatio !== undefined ? Math.min(100, utilizationRatio * 100) : undefined
  const barColor = pct !== undefined
    ? pct > 80 ? 'bg-negative' : pct > 60 ? 'bg-warning' : 'bg-positive'
    : 'bg-accent-cyan'
  const display = formatValue ? formatValue(value) : `${prefix}${value}${suffix}`

  return (
    <div className="py-1.5 border-b border-border-muted last:border-0">
      <div className="flex items-center gap-2">
        <div className="flex-1">
          <div className="flex items-center justify-between mb-0.5">
            <span className="font-mono text-[0.58rem] text-text-muted">{label}</span>
            <span className="font-mono text-[0.65rem] text-text-primary tabular-nums font-medium">{display}</span>
          </div>
          {pct !== undefined && (
            <div className="h-1 bg-bg-panel-raised rounded-full overflow-hidden">
              <div
                className={clsx('h-full rounded-full transition-all', barColor)}
                style={{ width: `${pct}%` }}
              />
            </div>
          )}
        </div>
        <input
          type="number"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={e => onChange(Number(e.target.value))}
          className="w-20 terminal-input h-6 text-[0.65rem] tabular-nums text-right"
        />
      </div>
    </div>
  )
}

function ToggleField({
  label,
  value,
  onChange,
  description,
}: {
  label: string
  value: boolean
  onChange: (v: boolean) => void
  description?: string
}) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border-muted last:border-0">
      <div>
        <span className="font-mono text-[0.58rem] text-text-muted">{label}</span>
        {description && (
          <p className="font-mono text-[0.5rem] text-text-dim mt-0.5">{description}</p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={clsx(
          'relative inline-flex h-4 w-7 items-center rounded-full border transition-colors',
          value ? 'bg-positive border-positive' : 'bg-bg-panel-raised border-border-subtle',
        )}
        role="switch"
        aria-checked={value}
      >
        <span
          className={clsx(
            'inline-block h-2.5 w-2.5 rounded-full bg-white transition-transform shadow-sm',
            value ? 'translate-x-3.5' : 'translate-x-0.5',
          )}
        />
      </button>
    </div>
  )
}

// ── Health Check Row ──────────────────────────────────────────────────────────

interface HealthItem {
  label: string
  current: number
  limit: number
  formatCurrent: (v: number) => string
  formatLimit: (v: number) => string
}

function HealthRow({ item }: { item: HealthItem }) {
  const ratio = item.limit > 0 ? item.current / item.limit : 0
  const color = ratio > 0.8 ? 'text-negative' : ratio > 0.6 ? 'text-warning' : 'text-positive'
  const barColor = ratio > 0.8 ? 'bg-negative' : ratio > 0.6 ? 'bg-warning' : 'bg-positive'

  return (
    <div className="py-1.5 border-b border-border-muted last:border-0">
      <div className="flex items-center justify-between mb-0.5">
        <span className="font-mono text-[0.58rem] text-text-muted">{item.label}</span>
        <span className={clsx('font-mono text-[0.6rem] tabular-nums', color)}>
          {item.formatCurrent(item.current)} / {item.formatLimit(item.limit)}
        </span>
      </div>
      <div className="h-1 bg-bg-panel-raised rounded-full overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all', barColor)}
          style={{ width: `${Math.min(100, ratio * 100)}%` }}
        />
      </div>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function RiskPolicyEditor({
  policy: initialPolicy,
  currentMetrics = DEFAULT_METRICS,
  onSave,
}: RiskPolicyEditorProps) {
  const [policy, setPolicy] = useState<RiskPolicy>(initialPolicy ?? DEFAULT_POLICY)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  const update = useCallback(<K extends keyof RiskPolicy>(key: K, value: RiskPolicy[K]) => {
    setPolicy(p => ({ ...p, [key]: value }))
    setDirty(true)
    setSaved(false)
  }, [])

  async function handleSave() {
    if (!showConfirm) {
      setShowConfirm(true)
      return
    }
    setSaving(true)
    try {
      const updated = { ...policy, updatedAt: Date.now() }
      await onSave?.(updated)
      setPolicy(updated)
      setDirty(false)
      setSaved(true)
      setShowConfirm(false)
      setTimeout(() => setSaved(false), 3000)
    } finally {
      setSaving(false)
    }
  }

  function handleReset() {
    setPolicy(DEFAULT_POLICY)
    setDirty(true)
    setSaved(false)
    setShowConfirm(false)
  }

  const healthItems: HealthItem[] = [
    {
      label: 'Total Exposure',
      current: currentMetrics.totalExposurePercent,
      limit: policy.maxPositionSizePercent * policy.maxPositionCount,
      formatCurrent: v => `${v.toFixed(1)}%`,
      formatLimit: v => `${v.toFixed(0)}%`,
    },
    {
      label: 'Daily Loss Used',
      current: Math.abs(currentMetrics.dailyPnl),
      limit: policy.maxDailyLossAbsolute,
      formatCurrent: v => fmt$(v),
      formatLimit: v => fmt$(v),
    },
    {
      label: 'Drawdown',
      current: currentMetrics.maxDrawdownPercent,
      limit: policy.maxDrawdownPercent,
      formatCurrent: v => `${v.toFixed(2)}%`,
      formatLimit: v => `${v.toFixed(0)}%`,
    },
    {
      label: 'Open Positions',
      current: currentMetrics.openPositionCount,
      limit: policy.maxPositionCount,
      formatCurrent: v => String(v),
      formatLimit: v => String(v),
    },
  ]

  return (
    <div className="flex flex-col h-full">
      <div className="panel-header">
        <span className="flex-1">◈ Risk Policy Editor</span>
        {dirty && (
          <span className="font-mono text-[0.55rem] text-warning uppercase tracking-widest animate-pulse">
            Unsaved
          </span>
        )}
        {saved && !dirty && (
          <span className="font-mono text-[0.55rem] text-positive uppercase tracking-widest">
            Saved
          </span>
        )}
      </div>

      <div className="px-2.5 pt-2 overflow-y-auto flex-1">

        <ToggleField
          label="Policy Enabled"
          value={policy.enabled}
          onChange={v => update('enabled', v)}
          description="Disable to bypass all risk checks (emergency only)"
        />

        {/* Position Limits */}
        <SectionHeader title="Position Limits" />
        <PolicyField
          label="Max Position Size"
          value={policy.maxPositionSizePercent}
          onChange={v => update('maxPositionSizePercent', v)}
          min={0.5} max={50} step={0.5} suffix="%"
          utilizationRatio={currentMetrics.totalExposurePercent / (policy.maxPositionSizePercent * 20)}
        />
        <PolicyField
          label="Max Single Position ($)"
          value={policy.maxSinglePositionValue}
          onChange={v => update('maxSinglePositionValue', v)}
          min={1000} max={500000} step={1000}
          formatValue={v => fmt$(v)}
        />
        <PolicyField
          label="Max Position Count"
          value={policy.maxPositionCount}
          onChange={v => update('maxPositionCount', v)}
          min={1} max={100} step={1}
          utilizationRatio={currentMetrics.openPositionCount / policy.maxPositionCount}
        />

        {/* Daily Loss Limits */}
        <SectionHeader title="Daily Loss Limits" />
        <PolicyField
          label="Max Daily Loss %"
          value={policy.maxDailyLossPercent}
          onChange={v => update('maxDailyLossPercent', v)}
          min={0.5} max={20} step={0.5} suffix="%"
          utilizationRatio={currentMetrics.dailyLossUsedPercent / 100}
        />
        <PolicyField
          label="Max Daily Loss ($)"
          value={policy.maxDailyLossAbsolute}
          onChange={v => update('maxDailyLossAbsolute', v)}
          min={100} max={100000} step={100}
          formatValue={v => fmt$(v)}
          utilizationRatio={Math.abs(currentMetrics.dailyPnl) / policy.maxDailyLossAbsolute}
        />
        <PolicyField
          label="Max Drawdown %"
          value={policy.maxDrawdownPercent}
          onChange={v => update('maxDrawdownPercent', v)}
          min={1} max={50} step={0.5} suffix="%"
          utilizationRatio={currentMetrics.maxDrawdownPercent / policy.maxDrawdownPercent}
        />

        {/* Order Limits */}
        <SectionHeader title="Order Limits" />
        <PolicyField
          label="Max Order Value ($)"
          value={policy.maxOrderValue}
          onChange={v => update('maxOrderValue', v)}
          min={100} max={500000} step={100}
          formatValue={v => fmt$(v)}
        />
        <PolicyField
          label="Max Order Quantity"
          value={policy.maxOrderQuantity}
          onChange={v => update('maxOrderQuantity', v)}
          min={1} max={100000} step={10}
        />

        {/* Concentration Limits */}
        <SectionHeader title="Concentration Limits" />
        <PolicyField
          label="Max Sector Exposure %"
          value={policy.maxSectorExposurePercent}
          onChange={v => update('maxSectorExposurePercent', v)}
          min={5} max={100} step={1} suffix="%"
        />
        <PolicyField
          label="Max Symbol Exposure %"
          value={policy.maxSymbolExposurePercent}
          onChange={v => update('maxSymbolExposurePercent', v)}
          min={1} max={50} step={0.5} suffix="%"
        />

        {/* Kill Switch */}
        <SectionHeader title="Kill Switch" />
        <ToggleField
          label="Kill Switch Enabled"
          value={policy.killSwitchEnabled}
          onChange={v => update('killSwitchEnabled', v)}
          description="Auto-halt trading when daily loss threshold is hit"
        />
        <PolicyField
          label="Trigger Threshold ($)"
          value={policy.killSwitchDailyLossThreshold}
          onChange={v => update('killSwitchDailyLossThreshold', v)}
          min={100} max={100000} step={100}
          formatValue={v => fmt$(v)}
          utilizationRatio={Math.abs(currentMetrics.dailyPnl) / policy.killSwitchDailyLossThreshold}
        />

        {/* Health check */}
        <SectionHeader title="Policy Health Check" />
        <div className="pb-3">
          {healthItems.map(item => (
            <HealthRow key={item.label} item={item} />
          ))}
        </div>
      </div>

      {/* Confirmation box */}
      {showConfirm && (
        <div className="mx-2.5 mb-2 p-2 bg-warning-bg border border-warning rounded-sm">
          <p className="font-mono text-[0.62rem] text-warning font-semibold uppercase tracking-wide mb-1">
            Confirm Policy Changes
          </p>
          <p className="font-mono text-[0.6rem] text-text-secondary mb-2">
            Policy changes take effect immediately and will apply to all new orders.
          </p>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setShowConfirm(false)}
              className="flex-1 py-1 font-mono text-[0.6rem] border border-border-subtle text-text-muted rounded-sm hover:border-accent-cyan transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="flex-1 py-1 font-mono text-[0.6rem] font-semibold bg-warning border border-warning text-bg-root rounded-sm hover:bg-warning-dim transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Confirm Save'}
            </button>
          </div>
        </div>
      )}

      {/* Footer actions */}
      <div className="flex gap-1.5 px-2.5 pb-2.5 pt-1.5 border-t border-border-subtle">
        <button
          type="button"
          onClick={handleReset}
          className="px-2.5 py-1.5 font-mono text-[0.6rem] border border-border-subtle text-text-muted rounded-sm hover:border-negative hover:text-negative transition-colors"
        >
          Reset Defaults
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={!dirty || saving}
          className={clsx(
            'flex-1 py-1.5 font-mono text-[0.68rem] font-bold uppercase tracking-wider rounded-sm border transition-colors',
            dirty
              ? 'bg-accent-cyan border-accent-cyan text-bg-root hover:bg-accent-cyan-dim'
              : 'bg-bg-panel border-border-subtle text-text-muted cursor-not-allowed',
            'disabled:opacity-50',
          )}
        >
          {saving ? 'Saving...' : 'Save Policy'}
        </button>
      </div>
    </div>
  )
}

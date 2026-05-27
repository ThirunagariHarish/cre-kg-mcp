import React, { useState, useCallback } from 'react'
import clsx from 'clsx'
import { Save, RotateCcw, X, AlertTriangle } from 'lucide-react'
import type { Agent, AgentConfig, TradingMode } from '@/types/agents'

/* ─────────────────────────────────────────────
   Props
───────────────────────────────────────────── */

interface AgentConfigEditorProps {
  /** The agent whose config is being edited */
  agent: Agent
  /** Called with the new config when user confirms save */
  onSave?: (config: AgentConfig) => Promise<void>
  /** Called when user cancels without saving */
  onCancel?: () => void
}

/* ─────────────────────────────────────────────
   Default config per agent name (fallback)
───────────────────────────────────────────── */

const DEFAULT_CONFIG: Partial<AgentConfig> = {
  trading_mode: 'moderate',
  scan_interval_seconds: 300,
  confidence_threshold: 65,
  stop_loss_pct: 25,
  profit_target_pct: 50,
  max_daily_trades: 3,
  signal_source: 'unusual_whales',
  broker: 'robinhood',
}

type BrokerOption = 'robinhood' | 'alpaca' | 'paper'

/* ─────────────────────────────────────────────
   Small UI helpers
───────────────────────────────────────────── */

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">
      {children}
    </span>
  )
}

function FieldGroup({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col gap-0.5">{children}</div>
}

interface NumberFieldProps {
  label: string
  value: number | undefined
  onChange: (v: number) => void
  min?: number
  max?: number
  suffix?: string
  className?: string
}
function NumberField({ label, value, onChange, min, max, suffix, className }: NumberFieldProps) {
  return (
    <FieldGroup>
      <FieldLabel>{label}</FieldLabel>
      <div className={clsx('flex items-center gap-1', className)}>
        <input
          type="number"
          value={value ?? ''}
          min={min}
          max={max}
          onChange={e => onChange(Number(e.target.value))}
          className="terminal-input w-full text-right"
          aria-label={label}
        />
        {suffix && <span className="font-mono text-[0.6rem] text-text-muted flex-shrink-0">{suffix}</span>}
      </div>
    </FieldGroup>
  )
}

/* ─────────────────────────────────────────────
   Risk/Reward Ratio Bar
───────────────────────────────────────────── */

function RiskRewardBar({ stopPct, targetPct }: { stopPct: number; targetPct: number }) {
  const ratio = stopPct > 0 ? (targetPct / stopPct) : 0
  const quality = ratio >= 3 ? 'text-positive' : ratio >= 2 ? 'text-warning' : 'text-negative'
  const stopWidth = Math.min((stopPct / (stopPct + targetPct)) * 100, 80)
  const targetWidth = Math.min((targetPct / (stopPct + targetPct)) * 100, 80)

  return (
    <div className="flex flex-col gap-1.5 p-2.5 bg-bg-panel-raised border border-border-subtle rounded-sm">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-wider">Risk/Reward Preview</span>
        <span className={clsx('font-mono text-[0.68rem] font-semibold tabular-nums', quality)}>
          1 : {ratio.toFixed(2)}
        </span>
      </div>
      <div className="flex items-center gap-1 h-3">
        {/* Stop loss bar (red, left) */}
        <div
          className="h-full bg-negative-dim rounded-sm flex items-center justify-center"
          style={{ width: `${stopWidth}%`, minWidth: 20 }}
        >
          <span className="font-mono text-[0.45rem] text-negative truncate px-0.5">-{stopPct}%</span>
        </div>
        {/* Separator */}
        <div className="w-px h-3 bg-border-subtle flex-shrink-0" />
        {/* Target bar (green, right) */}
        <div
          className="h-full bg-positive-dim rounded-sm flex items-center justify-center"
          style={{ width: `${targetWidth}%`, minWidth: 20 }}
        >
          <span className="font-mono text-[0.45rem] text-positive truncate px-0.5">+{targetPct}%</span>
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className="font-mono text-[0.52rem] text-negative">Stop: -{stopPct}%</span>
        <span className="font-mono text-[0.52rem] text-positive">Target: +{targetPct}%</span>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Confirmation dialog
───────────────────────────────────────────── */

interface ConfirmDialogProps {
  onConfirm: () => void
  onCancel: () => void
}
function ConfirmDialog({ onConfirm, onCancel }: ConfirmDialogProps) {
  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-bg-root/80 backdrop-blur-sm">
      <div className="bg-bg-panel border border-border-active shadow-panel-active rounded-sm p-4 max-w-xs w-full mx-4">
        <div className="flex items-start gap-2 mb-3">
          <AlertTriangle size={14} className="text-warning flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-mono text-[0.7rem] text-text-primary font-semibold mb-1">Confirm Save</p>
            <p className="font-mono text-[0.6rem] text-text-secondary leading-relaxed">
              This will restart the agent with the new configuration. Continue?
            </p>
          </div>
        </div>
        <div className="flex gap-2 justify-end">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 font-mono text-[0.6rem] border border-border-subtle text-text-muted hover:text-text-secondary rounded-sm transition-colors"
          >
            CANCEL
          </button>
          <button
            onClick={onConfirm}
            className="px-3 py-1.5 font-mono text-[0.6rem] border border-positive text-positive hover:bg-positive-bg rounded-sm transition-colors"
          >
            CONFIRM SAVE
          </button>
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Main Component
───────────────────────────────────────────── */

export default function AgentConfigEditor({ agent, onSave, onCancel }: AgentConfigEditorProps) {
  const initial: AgentConfig = {
    ...DEFAULT_CONFIG,
    ...agent.config,
    // Normalize confidence: stored as 0-1 in types but displayed as 0-100
    confidence_threshold: agent.config.confidence_threshold != null
      ? (agent.config.confidence_threshold > 1 ? agent.config.confidence_threshold : agent.config.confidence_threshold * 100)
      : 65,
  }

  const [form, setForm] = useState<AgentConfig>(initial)
  const [isDirty, setIsDirty] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [saving, setSaving] = useState(false)

  const update = useCallback(<K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) => {
    setForm(prev => ({ ...prev, [key]: value }))
    setIsDirty(true)
  }, [])

  const handleSave = () => setShowConfirm(true)

  const handleConfirm = async () => {
    setShowConfirm(false)
    setSaving(true)
    try {
      const saved: AgentConfig = {
        ...form,
        // Normalize confidence back to 0-1 for storage
        confidence_threshold: (form.confidence_threshold ?? 65) / 100,
      }
      await onSave?.(saved)
      setIsDirty(false)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    setForm(initial)
    setIsDirty(false)
  }

  const catColor = agent.category === 'ALGORITHM' ? 'text-accent-cyan border-accent-cyan'
    : agent.category === 'DISCORD' ? 'text-accent-purple border-accent-purple'
    : agent.category === 'AI' ? 'text-accent-amber border-accent-amber'
    : agent.category === 'DATA' ? 'text-info border-info'
    : agent.category === 'OPTIONS' ? 'text-positive border-positive'
    : 'text-text-secondary border-border-subtle'

  return (
    <div className="relative flex flex-col h-full overflow-hidden bg-bg-panel">
      {showConfirm && <ConfirmDialog onConfirm={handleConfirm} onCancel={() => setShowConfirm(false)} />}

      {/* Header */}
      <div className="panel-header">
        {isDirty && <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan flex-shrink-0" title="Unsaved changes" />}
        <span className="flex-1 truncate">◈ Agent Config — {agent.displayName}</span>
        <span className={clsx('font-mono text-[0.52rem] px-1 py-px border rounded-sm flex-shrink-0', catColor)}>
          {agent.category}
        </span>
        {onCancel && (
          <button onClick={onCancel} className="text-text-muted hover:text-text-primary transition-colors ml-1" aria-label="Close editor">
            <X size={11} />
          </button>
        )}
      </div>

      {/* Form */}
      <div className="flex-1 overflow-y-auto min-h-0 p-3 space-y-4">
        {/* Identity */}
        <section>
          <p className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-2 border-b border-border-subtle pb-1">
            Identity
          </p>
          <div className="grid grid-cols-1 gap-2">
            <FieldGroup>
              <FieldLabel>Name</FieldLabel>
              <input
                type="text"
                value={form.name}
                readOnly
                className="terminal-input opacity-50 cursor-not-allowed"
                aria-label="Agent name (read-only)"
              />
            </FieldGroup>
            <FieldGroup>
              <FieldLabel>Description</FieldLabel>
              <textarea
                value={form.description ?? ''}
                onChange={e => update('description', e.target.value)}
                rows={3}
                className="terminal-input resize-none leading-relaxed"
                aria-label="Agent description"
              />
            </FieldGroup>
          </div>
        </section>

        {/* Execution */}
        <section>
          <p className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-2 border-b border-border-subtle pb-1">
            Execution
          </p>
          <div className="grid grid-cols-2 gap-2">
            <FieldGroup>
              <FieldLabel>Trading Mode</FieldLabel>
              <select
                value={form.trading_mode ?? 'moderate'}
                onChange={e => update('trading_mode', e.target.value as TradingMode)}
                className="terminal-input"
                aria-label="Trading mode"
              >
                <option value="aggressive">Aggressive</option>
                <option value="moderate">Moderate</option>
                <option value="conservative">Conservative</option>
                <option value="paper">Paper</option>
              </select>
            </FieldGroup>
            <NumberField
              label="Scan Interval"
              value={form.scan_interval_seconds}
              onChange={v => update('scan_interval_seconds', v)}
              min={10}
              max={86400}
              suffix="sec"
            />
            <NumberField
              label="Max Daily Trades"
              value={form.max_daily_trades}
              onChange={v => update('max_daily_trades', v)}
              min={0}
              max={50}
              suffix="trades"
            />
            <FieldGroup>
              <FieldLabel>Signal Source</FieldLabel>
              <input
                type="text"
                value={form.signal_source ?? ''}
                onChange={e => update('signal_source', e.target.value)}
                className="terminal-input"
                aria-label="Signal source"
              />
            </FieldGroup>
            <FieldGroup>
              <FieldLabel>Broker</FieldLabel>
              <select
                value={form.broker ?? 'robinhood'}
                onChange={e => update('broker', e.target.value as BrokerOption)}
                className="terminal-input"
                aria-label="Broker"
              >
                <option value="robinhood">Robinhood</option>
                <option value="alpaca">Alpaca</option>
                <option value="paper">Paper</option>
              </select>
            </FieldGroup>
          </div>
        </section>

        {/* Confidence */}
        <section>
          <p className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-2 border-b border-border-subtle pb-1">
            Signal Quality
          </p>
          <FieldGroup>
            <div className="flex items-center justify-between">
              <FieldLabel>Confidence Threshold</FieldLabel>
              <span className="font-mono text-[0.65rem] text-accent-cyan font-semibold">
                {Math.round(form.confidence_threshold ?? 65)}%
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={form.confidence_threshold ?? 65}
              onChange={e => update('confidence_threshold', Number(e.target.value))}
              className="w-full accent-[#ff6600] h-1 rounded-full cursor-pointer"
              aria-label="Confidence threshold"
            />
            <div className="flex justify-between">
              <span className="font-mono text-[0.5rem] text-text-muted">0% (any)</span>
              <span className="font-mono text-[0.5rem] text-text-muted">100% (strict)</span>
            </div>
          </FieldGroup>
        </section>

        {/* Risk */}
        <section>
          <p className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-2 border-b border-border-subtle pb-1">
            Risk Management
          </p>
          <div className="grid grid-cols-2 gap-2 mb-3">
            <NumberField
              label="Stop Loss"
              value={form.stop_loss_pct}
              onChange={v => update('stop_loss_pct', v)}
              min={1}
              max={100}
              suffix="%"
            />
            <NumberField
              label="Profit Target"
              value={form.profit_target_pct}
              onChange={v => update('profit_target_pct', v)}
              min={1}
              max={1000}
              suffix="%"
            />
          </div>
          {/* Risk/reward preview */}
          <RiskRewardBar
            stopPct={form.stop_loss_pct ?? 25}
            targetPct={form.profit_target_pct ?? 50}
          />
        </section>
      </div>

      {/* Footer actions */}
      <div className="flex items-center gap-2 p-2.5 border-t border-border-subtle flex-shrink-0 bg-bg-panel">
        <button
          onClick={handleReset}
          className="flex items-center gap-1 px-2 py-1.5 font-mono text-[0.6rem] border border-border-subtle text-text-muted hover:text-text-secondary rounded-sm transition-colors"
          title="Reset to current saved config"
          aria-label="Reset to defaults"
        >
          <RotateCcw size={9} />
          RESET
        </button>
        <div className="flex-1" />
        {onCancel && (
          <button
            onClick={onCancel}
            className="px-3 py-1.5 font-mono text-[0.62rem] border border-border-subtle text-text-muted hover:text-text-secondary rounded-sm transition-colors"
            aria-label="Cancel"
          >
            CANCEL
          </button>
        )}
        <button
          onClick={handleSave}
          disabled={!isDirty || saving}
          className={clsx(
            'flex items-center gap-1 px-3 py-1.5 font-mono text-[0.62rem] border rounded-sm transition-colors',
            isDirty && !saving
              ? 'border-positive text-positive hover:bg-positive-bg cursor-pointer'
              : 'border-border-subtle text-text-muted cursor-not-allowed opacity-50'
          )}
          aria-label="Save configuration"
        >
          <Save size={9} />
          {saving ? 'SAVING...' : 'SAVE'}
        </button>
      </div>
    </div>
  )
}

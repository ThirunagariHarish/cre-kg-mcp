import React, { useState, useCallback } from 'react'
import clsx from 'clsx'
import { ChevronRight, ChevronLeft, Check, X, AlertTriangle } from 'lucide-react'
import type { AgentConfig, TradingMode } from '@/types/agents'

/* ─────────────────────────────────────────────
   Props
───────────────────────────────────────────── */

interface AgentCreationWizardProps {
  /** Called when agent creation is confirmed */
  onComplete?: (config: AgentConfig) => void
  /** Called when user cancels */
  onCancel?: () => void
}

/* ─────────────────────────────────────────────
   Templates
───────────────────────────────────────────── */

interface AgentTemplate {
  id: string
  icon: string
  name: string
  description: string
  category: string
  categoryColor: string
  defaultConfig: Partial<AgentConfig>
}

const TEMPLATES: AgentTemplate[] = [
  {
    id: 'breakout', icon: '⚡', name: 'Breakout Trader',
    description: 'Scans UW options flow for golden sweeps and blocks. Targets momentum breakouts above multi-week highs.',
    category: 'ALGO', categoryColor: 'text-accent-cyan border-accent-cyan',
    defaultConfig: { trading_mode: 'aggressive', scan_interval_seconds: 300, stop_loss_pct: 35, profit_target_pct: 100, max_daily_trades: 3, signal_source: 'unusual_whales', confidence_threshold: 65, broker: 'robinhood' },
  },
  {
    id: 'discord', icon: '💬', name: 'Discord Signal Reader',
    description: 'Monitors Discord channels for trade signals. Parses options alerts from professional traders.',
    category: 'DISC', categoryColor: 'text-accent-purple border-accent-purple',
    defaultConfig: { trading_mode: 'moderate', scan_interval_seconds: 0, stop_loss_pct: 25, profit_target_pct: 60, max_daily_trades: 3, signal_source: 'discord', confidence_threshold: 60, broker: 'robinhood' },
  },
  {
    id: 'condor', icon: '🦅', name: 'Options Iron Condor',
    description: 'Opens iron condors on high-IV underlyings. 20-delta short legs, 30-60 DTE. Targets 50% profit.',
    category: 'OPTS', categoryColor: 'text-positive border-positive',
    defaultConfig: { trading_mode: 'paper', scan_interval_seconds: 86400, stop_loss_pct: 200, profit_target_pct: 50, max_daily_trades: 1, signal_source: 'iv_rank', confidence_threshold: 70, broker: 'paper' },
  },
  {
    id: 'ai_sentiment', icon: '🤖', name: 'AI Sentiment',
    description: 'Uses NLP transformers to analyze Reddit, Twitter, and news sentiment. Trades sentiment spikes.',
    category: 'AI', categoryColor: 'text-accent-amber border-accent-amber',
    defaultConfig: { trading_mode: 'moderate', scan_interval_seconds: 3600, stop_loss_pct: 20, profit_target_pct: 40, max_daily_trades: 2, signal_source: 'nlp_sentiment', confidence_threshold: 75, broker: 'robinhood' },
  },
  {
    id: 'dark_pool', icon: '🔮', name: 'Dark Pool',
    description: 'Follows large dark pool block prints. Enters when 3+ blocks accumulate at same strike in 15 min.',
    category: 'ALGO', categoryColor: 'text-accent-cyan border-accent-cyan',
    defaultConfig: { trading_mode: 'aggressive', scan_interval_seconds: 900, stop_loss_pct: 20, profit_target_pct: 60, max_daily_trades: 2, signal_source: 'dark_pool', confidence_threshold: 70, broker: 'robinhood' },
  },
  {
    id: 'momentum', icon: '📈', name: 'Momentum',
    description: 'Rides strong momentum moves with volume confirmation. Uses relative strength and sector rotation.',
    category: 'ALGO', categoryColor: 'text-accent-cyan border-accent-cyan',
    defaultConfig: { trading_mode: 'moderate', scan_interval_seconds: 600, stop_loss_pct: 15, profit_target_pct: 30, max_daily_trades: 4, signal_source: 'screener', confidence_threshold: 65, broker: 'robinhood' },
  },
  {
    id: 'mean_rev', icon: '↩', name: 'Mean Reversion',
    description: 'Fades oversold/overbought stocks back to 20-day moving average. Counter-trend with tight stops.',
    category: 'ALGO', categoryColor: 'text-accent-cyan border-accent-cyan',
    defaultConfig: { trading_mode: 'moderate', scan_interval_seconds: 3600, stop_loss_pct: 10, profit_target_pct: 20, max_daily_trades: 3, signal_source: 'screener', confidence_threshold: 70, broker: 'robinhood' },
  },
  {
    id: 'custom', icon: '⚙', name: 'Custom',
    description: 'Start from scratch with blank configuration. Manually define all parameters.',
    category: 'ALGO', categoryColor: 'text-text-muted border-border-subtle',
    defaultConfig: { trading_mode: 'paper', scan_interval_seconds: 300, stop_loss_pct: 25, profit_target_pct: 50, max_daily_trades: 3, confidence_threshold: 65, broker: 'paper' },
  },
]

/* ─────────────────────────────────────────────
   Wizard state
───────────────────────────────────────────── */

type Step = 1 | 2 | 3 | 4

interface WizardState {
  template: AgentTemplate | null
  config: AgentConfig
  killConditions: {
    dailyLossLimit: number
    consecutiveLosses: number
    drawdownPct: number
  }
}

const EMPTY_CONFIG: AgentConfig = {
  name: '',
  description: '',
  trading_mode: 'moderate',
  scan_interval_seconds: 300,
  confidence_threshold: 65,
  stop_loss_pct: 25,
  profit_target_pct: 50,
  max_daily_trades: 3,
  signal_source: '',
  broker: 'paper',
}

/* ─────────────────────────────────────────────
   Step indicator
───────────────────────────────────────────── */

const STEPS = [
  { n: 1 as Step, label: 'Template' },
  { n: 2 as Step, label: 'Configure' },
  { n: 3 as Step, label: 'Risk' },
  { n: 4 as Step, label: 'Review' },
]

function StepIndicator({ current }: { current: Step }) {
  return (
    <div className="flex items-center px-4 py-3 border-b border-border-subtle flex-shrink-0">
      {STEPS.map((step, i) => {
        const done = current > step.n
        const active = current === step.n
        return (
          <React.Fragment key={step.n}>
            <div className="flex items-center gap-1.5">
              <div className={clsx(
                'w-5 h-5 rounded-full flex items-center justify-center font-mono text-[0.55rem] font-semibold flex-shrink-0 transition-colors',
                done ? 'bg-positive text-black'
                  : active ? 'bg-accent-cyan text-black'
                  : 'bg-bg-panel-raised text-text-muted border border-border-subtle'
              )}>
                {done ? <Check size={8} /> : step.n}
              </div>
              <span className={clsx(
                'font-mono text-[0.58rem] uppercase tracking-wide hidden sm:block',
                active ? 'text-accent-cyan' : done ? 'text-positive' : 'text-text-muted'
              )}>
                {step.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={clsx('flex-1 h-px mx-2', done ? 'bg-positive' : 'bg-border-subtle')} />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}

/* ─────────────────────────────────────────────
   Step 1: Template chooser
───────────────────────────────────────────── */

function Step1Templates({ selected, onSelect }: {
  selected: AgentTemplate | null
  onSelect: (t: AgentTemplate) => void
}) {
  return (
    <div className="flex-1 overflow-y-auto min-h-0 p-3">
      <p className="font-mono text-[0.6rem] text-text-secondary mb-3 leading-relaxed">
        Choose a template to start from. You can customize all settings in the next steps.
      </p>
      <div className="grid grid-cols-2 gap-2">
        {TEMPLATES.map(t => (
          <button
            key={t.id}
            onClick={() => onSelect(t)}
            className={clsx(
              'text-left p-3 border rounded-sm transition-all bg-bg-panel-raised',
              selected?.id === t.id
                ? 'border-accent-cyan shadow-panel-active'
                : 'border-border-subtle hover:border-border-active'
            )}
            aria-pressed={selected?.id === t.id}
          >
            <div className="flex items-start gap-2 mb-1.5">
              <span className="text-base leading-none flex-shrink-0">{t.icon}</span>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="font-mono text-[0.68rem] font-semibold text-text-primary">{t.name}</span>
                </div>
                <span className={clsx('font-mono text-[0.5rem] px-1 py-px border rounded-sm', t.categoryColor)}>
                  {t.category}
                </span>
              </div>
            </div>
            <p className="font-mono text-[0.55rem] text-text-muted leading-relaxed line-clamp-3">
              {t.description}
            </p>
            {selected?.id === t.id && (
              <div className="mt-2 flex items-center gap-1">
                <Check size={9} className="text-accent-cyan" />
                <span className="font-mono text-[0.52rem] text-accent-cyan">Selected</span>
              </div>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Step 2: Configure form
───────────────────────────────────────────── */

function Step2Configure({ config, onChange }: {
  config: AgentConfig
  onChange: (key: keyof AgentConfig, value: AgentConfig[keyof AgentConfig]) => void
}) {
  return (
    <div className="flex-1 overflow-y-auto min-h-0 p-3 space-y-3">
      <p className="font-mono text-[0.6rem] text-text-secondary leading-relaxed">
        Configure your agent's core settings. Fields marked with * are required.
      </p>
      <div className="grid grid-cols-1 gap-3">
        {/* Name */}
        <div className="flex flex-col gap-0.5">
          <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">
            Agent Name *
          </label>
          <input
            type="text"
            value={config.name}
            onChange={e => onChange('name', e.target.value)}
            placeholder="e.g. my_breakout_trader"
            className="terminal-input"
            aria-label="Agent name"
            aria-required="true"
          />
          <span className="font-mono text-[0.5rem] text-text-muted">Lowercase, underscores only. Used as file/folder name.</span>
        </div>

        {/* Description */}
        <div className="flex flex-col gap-0.5">
          <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Description</label>
          <textarea
            value={config.description ?? ''}
            onChange={e => onChange('description', e.target.value)}
            rows={2}
            className="terminal-input resize-none"
            aria-label="Agent description"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          {/* Trading Mode */}
          <div className="flex flex-col gap-0.5">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Trading Mode</label>
            <select
              value={config.trading_mode ?? 'moderate'}
              onChange={e => onChange('trading_mode', e.target.value as TradingMode)}
              className="terminal-input"
              aria-label="Trading mode"
            >
              <option value="paper">Paper (simulation)</option>
              <option value="conservative">Conservative</option>
              <option value="moderate">Moderate</option>
              <option value="aggressive">Aggressive</option>
            </select>
          </div>

          {/* Broker */}
          <div className="flex flex-col gap-0.5">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Broker</label>
            <select
              value={config.broker ?? 'paper'}
              onChange={e => onChange('broker', e.target.value)}
              className="terminal-input"
              aria-label="Broker"
            >
              <option value="paper">Paper</option>
              <option value="robinhood">Robinhood</option>
              <option value="alpaca">Alpaca</option>
            </select>
          </div>

          {/* Scan Interval */}
          <div className="flex flex-col gap-0.5">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Scan Interval (sec)</label>
            <input
              type="number"
              value={config.scan_interval_seconds ?? 300}
              onChange={e => onChange('scan_interval_seconds', Number(e.target.value))}
              min={0}
              max={86400}
              className="terminal-input"
              aria-label="Scan interval in seconds"
            />
          </div>

          {/* Max Daily Trades */}
          <div className="flex flex-col gap-0.5">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Max Daily Trades</label>
            <input
              type="number"
              value={config.max_daily_trades ?? 3}
              onChange={e => onChange('max_daily_trades', Number(e.target.value))}
              min={0}
              max={50}
              className="terminal-input"
              aria-label="Maximum daily trades"
            />
          </div>

          {/* Signal Source */}
          <div className="flex flex-col gap-0.5 col-span-2">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Signal Source</label>
            <input
              type="text"
              value={config.signal_source ?? ''}
              onChange={e => onChange('signal_source', e.target.value)}
              placeholder="e.g. unusual_whales, discord, screener"
              className="terminal-input"
              aria-label="Signal source"
            />
          </div>
        </div>

        {/* Confidence Threshold */}
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center justify-between">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Confidence Threshold</label>
            <span className="font-mono text-[0.65rem] text-accent-cyan font-semibold">
              {Math.round(config.confidence_threshold ?? 65)}%
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={config.confidence_threshold ?? 65}
            onChange={e => onChange('confidence_threshold', Number(e.target.value))}
            className="w-full accent-[#ff6600] h-1 cursor-pointer"
            aria-label="Confidence threshold"
          />
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Step 3: Risk settings
───────────────────────────────────────────── */

interface KillConditions {
  dailyLossLimit: number
  consecutiveLosses: number
  drawdownPct: number
}

function Step3Risk({ config, onChange, kill, onKillChange }: {
  config: AgentConfig
  onChange: (key: keyof AgentConfig, value: AgentConfig[keyof AgentConfig]) => void
  kill: KillConditions
  onKillChange: (key: keyof KillConditions, value: number) => void
}) {
  const ratio = (config.stop_loss_pct ?? 25) > 0
    ? ((config.profit_target_pct ?? 50) / (config.stop_loss_pct ?? 25))
    : 0

  return (
    <div className="flex-1 overflow-y-auto min-h-0 p-3 space-y-4">
      {/* Position risk */}
      <section>
        <p className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-2 border-b border-border-subtle pb-1">
          Position Risk
        </p>
        <div className="grid grid-cols-2 gap-2 mb-3">
          <div className="flex flex-col gap-0.5">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Stop Loss %</label>
            <div className="flex items-center gap-1">
              <input
                type="number"
                value={config.stop_loss_pct ?? 25}
                onChange={e => onChange('stop_loss_pct', Number(e.target.value))}
                min={1}
                max={100}
                className="terminal-input text-right"
                aria-label="Stop loss percentage"
              />
              <span className="font-mono text-[0.6rem] text-negative flex-shrink-0">%</span>
            </div>
          </div>
          <div className="flex flex-col gap-0.5">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Profit Target %</label>
            <div className="flex items-center gap-1">
              <input
                type="number"
                value={config.profit_target_pct ?? 50}
                onChange={e => onChange('profit_target_pct', Number(e.target.value))}
                min={1}
                max={1000}
                className="terminal-input text-right"
                aria-label="Profit target percentage"
              />
              <span className="font-mono text-[0.6rem] text-positive flex-shrink-0">%</span>
            </div>
          </div>
        </div>

        {/* R:R ratio bar */}
        <div className="p-2.5 bg-bg-panel-raised border border-border-subtle rounded-sm">
          <div className="flex items-center justify-between mb-2">
            <span className="font-mono text-[0.52rem] text-text-muted uppercase tracking-wider">Risk / Reward</span>
            <span className={clsx(
              'font-mono text-[0.68rem] font-semibold',
              ratio >= 3 ? 'text-positive' : ratio >= 2 ? 'text-warning' : 'text-negative'
            )}>
              1 : {ratio.toFixed(2)}
            </span>
          </div>
          <div className="flex gap-1 h-3">
            <div
              className="bg-negative-dim rounded-sm flex items-center justify-center"
              style={{ width: `${Math.min(((config.stop_loss_pct ?? 25) / ((config.stop_loss_pct ?? 25) + (config.profit_target_pct ?? 50))) * 100, 80)}%`, minWidth: 24 }}
            >
              <span className="font-mono text-[0.45rem] text-negative">STOP</span>
            </div>
            <div
              className="bg-positive-dim rounded-sm flex items-center justify-center"
              style={{ width: `${Math.min(((config.profit_target_pct ?? 50) / ((config.stop_loss_pct ?? 25) + (config.profit_target_pct ?? 50))) * 100, 80)}%`, minWidth: 24 }}
            >
              <span className="font-mono text-[0.45rem] text-positive">TARGET</span>
            </div>
          </div>
        </div>
      </section>

      {/* Kill switch conditions */}
      <section>
        <p className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest mb-2 border-b border-border-subtle pb-1">
          Kill Switch Conditions
        </p>
        <p className="font-mono text-[0.55rem] text-text-secondary mb-2 leading-relaxed">
          Agent will auto-pause and alert if any condition is triggered.
        </p>
        <div className="grid grid-cols-1 gap-2">
          <div className="flex flex-col gap-0.5">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Daily Loss Limit ($)</label>
            <div className="flex items-center gap-1">
              <span className="font-mono text-[0.6rem] text-text-muted flex-shrink-0">$</span>
              <input
                type="number"
                value={kill.dailyLossLimit}
                onChange={e => onKillChange('dailyLossLimit', Number(e.target.value))}
                min={0}
                className="terminal-input"
                aria-label="Daily loss limit in dollars"
              />
            </div>
          </div>
          <div className="flex flex-col gap-0.5">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Consecutive Loss Limit</label>
            <input
              type="number"
              value={kill.consecutiveLosses}
              onChange={e => onKillChange('consecutiveLosses', Number(e.target.value))}
              min={1}
              max={20}
              className="terminal-input"
              aria-label="Consecutive loss limit"
            />
          </div>
          <div className="flex flex-col gap-0.5">
            <label className="font-mono text-[0.58rem] text-text-muted uppercase tracking-wider">Portfolio Drawdown %</label>
            <div className="flex items-center gap-1">
              <input
                type="number"
                value={kill.drawdownPct}
                onChange={e => onKillChange('drawdownPct', Number(e.target.value))}
                min={0}
                max={100}
                className="terminal-input"
                aria-label="Portfolio drawdown kill switch percentage"
              />
              <span className="font-mono text-[0.6rem] text-text-muted flex-shrink-0">%</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Step 4: Review
───────────────────────────────────────────── */

function Step4Review({ template, config, kill }: {
  template: AgentTemplate | null
  config: AgentConfig
  kill: KillConditions
}) {
  const sections: Array<{ title: string; rows: Array<[string, string]> }> = [
    {
      title: 'Template',
      rows: [[
        'Based on', template ? `${template.icon} ${template.name}` : 'Custom'
      ]],
    },
    {
      title: 'Identity',
      rows: [
        ['Name', config.name || '(unnamed)'],
        ['Description', config.description || '—'],
        ['Trading Mode', config.trading_mode ?? 'moderate'],
        ['Broker', config.broker ?? 'paper'],
      ],
    },
    {
      title: 'Execution',
      rows: [
        ['Scan Interval', `${config.scan_interval_seconds ?? 300}s`],
        ['Max Daily Trades', String(config.max_daily_trades ?? 3)],
        ['Signal Source', config.signal_source || '—'],
        ['Confidence', `${Math.round(config.confidence_threshold ?? 65)}%`],
      ],
    },
    {
      title: 'Risk',
      rows: [
        ['Stop Loss', `${config.stop_loss_pct ?? 25}%`],
        ['Profit Target', `${config.profit_target_pct ?? 50}%`],
        ['Daily Loss Limit', `$${kill.dailyLossLimit}`],
        ['Consecutive Loss Limit', String(kill.consecutiveLosses)],
        ['Drawdown Kill', `${kill.drawdownPct}%`],
      ],
    },
  ]

  return (
    <div className="flex-1 overflow-y-auto min-h-0 p-3 space-y-3">
      <p className="font-mono text-[0.6rem] text-text-secondary leading-relaxed">
        Review all settings before creating. The agent will start in <span className="text-warning">PAUSED</span> mode.
      </p>
      {sections.map(sec => (
        <div key={sec.title} className="bg-bg-panel-raised border border-border-subtle rounded-sm overflow-hidden">
          <div className="px-2.5 py-1.5 border-b border-border-subtle">
            <span className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest">{sec.title}</span>
          </div>
          <div className="px-2.5 py-1.5 space-y-0.5">
            {sec.rows.map(([k, v]) => (
              <div key={k} className="flex justify-between items-baseline">
                <span className="font-mono text-[0.58rem] text-text-muted">{k}</span>
                <span className="font-mono text-[0.62rem] text-text-primary tabular-nums">{v}</span>
              </div>
            ))}
          </div>
        </div>
      ))}

      {config.trading_mode !== 'paper' && (
        <div className="flex items-start gap-2 p-2.5 border border-warning-dim rounded-sm bg-warning-bg">
          <AlertTriangle size={11} className="text-warning flex-shrink-0 mt-0.5" />
          <p className="font-mono text-[0.58rem] text-warning leading-relaxed">
            This agent is configured for live trading mode ({config.trading_mode}).
            Ensure your broker credentials are configured and paper-test before enabling.
          </p>
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────
   Main Wizard
───────────────────────────────────────────── */

export default function AgentCreationWizard({ onComplete, onCancel }: AgentCreationWizardProps) {
  const [step, setStep] = useState<Step>(1)
  const [state, setState] = useState<WizardState>({
    template: null,
    config: { ...EMPTY_CONFIG },
    killConditions: { dailyLossLimit: 500, consecutiveLosses: 3, drawdownPct: 10 },
  })
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)
  const [created, setCreated] = useState(false)

  const isDirty = state.config.name !== '' || state.template !== null

  const updateConfig = useCallback((key: keyof AgentConfig, value: AgentConfig[keyof AgentConfig]) => {
    setState(prev => ({ ...prev, config: { ...prev.config, [key]: value } }))
  }, [])

  const updateKill = useCallback((key: keyof WizardState['killConditions'], value: number) => {
    setState(prev => ({ ...prev, killConditions: { ...prev.killConditions, [key]: value } }))
  }, [])

  const selectTemplate = useCallback((t: AgentTemplate) => {
    setState(prev => ({
      ...prev,
      template: t,
      config: { ...EMPTY_CONFIG, ...t.defaultConfig, name: prev.config.name },
    }))
  }, [])

  // Validation per step
  const canProceed: Record<Step, boolean> = {
    1: state.template !== null,
    2: state.config.name.trim().length > 0,
    3: true,
    4: true,
  }

  const handleNext = () => {
    if (step < 4 && canProceed[step]) setStep(s => (s + 1) as Step)
  }
  const handleBack = () => {
    if (step > 1) setStep(s => (s - 1) as Step)
  }
  const handleCancel = () => {
    if (isDirty) setShowCancelConfirm(true)
    else onCancel?.()
  }
  const handleCreate = () => {
    const finalConfig: AgentConfig = {
      ...state.config,
      confidence_threshold: (state.config.confidence_threshold ?? 65) / 100,
    }
    onComplete?.(finalConfig)
    setCreated(true)
  }

  if (created) {
    return (
      <div className="flex flex-col h-full items-center justify-center bg-bg-panel gap-4 p-6">
        <div className="w-12 h-12 rounded-full bg-positive-bg border border-positive flex items-center justify-center">
          <Check size={24} className="text-positive" />
        </div>
        <div className="text-center">
          <p className="font-mono text-[0.8rem] text-positive font-semibold mb-1">Agent Created</p>
          <p className="font-mono text-[0.62rem] text-text-secondary">
            <span className="text-accent-cyan">{state.config.name}</span> has been created in PAUSED mode.
          </p>
        </div>
        <div className="text-left bg-bg-panel-raised border border-border-subtle rounded-sm p-3 max-w-xs w-full">
          <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-2">Next Steps</p>
          {[
            '1. Review config file in agents/ folder',
            '2. Verify broker API credentials',
            '3. Paper-test for at least 2 weeks',
            '4. Enable live trading via RESUME',
          ].map(s => (
            <p key={s} className="font-mono text-[0.6rem] text-text-secondary py-0.5">{s}</p>
          ))}
        </div>
        <button
          onClick={onCancel}
          className="px-4 py-1.5 font-mono text-[0.65rem] border border-accent-cyan text-accent-cyan hover:bg-bg-panel-raised rounded-sm transition-colors"
        >
          CLOSE
        </button>
      </div>
    )
  }

  return (
    <div className="relative flex flex-col h-full overflow-hidden bg-bg-panel">
      {/* Cancel confirm */}
      {showCancelConfirm && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-bg-root/80">
          <div className="bg-bg-panel border border-border-active shadow-panel-active rounded-sm p-4 max-w-xs w-full mx-4">
            <p className="font-mono text-[0.7rem] text-text-primary font-semibold mb-1">Discard changes?</p>
            <p className="font-mono text-[0.6rem] text-text-secondary mb-3">Exit wizard? All unsaved changes will be lost.</p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowCancelConfirm(false)}
                className="px-3 py-1.5 font-mono text-[0.6rem] border border-border-subtle text-text-muted hover:text-text-secondary rounded-sm"
              >
                KEEP EDITING
              </button>
              <button
                onClick={() => onCancel?.()}
                className="px-3 py-1.5 font-mono text-[0.6rem] border border-negative text-negative hover:bg-negative-bg rounded-sm"
              >
                DISCARD
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ New Agent</span>
        <button onClick={handleCancel} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Cancel wizard">
          <X size={11} />
        </button>
      </div>

      {/* Step indicator */}
      <StepIndicator current={step} />

      {/* Step content */}
      {step === 1 && (
        <Step1Templates selected={state.template} onSelect={selectTemplate} />
      )}
      {step === 2 && (
        <Step2Configure config={state.config} onChange={updateConfig} />
      )}
      {step === 3 && (
        <Step3Risk
          config={state.config}
          onChange={updateConfig}
          kill={state.killConditions}
          onKillChange={updateKill}
        />
      )}
      {step === 4 && (
        <Step4Review template={state.template} config={state.config} kill={state.killConditions} />
      )}

      {/* Navigation */}
      <div className="flex items-center gap-2 p-2.5 border-t border-border-subtle flex-shrink-0">
        <button
          onClick={handleBack}
          disabled={step === 1}
          className={clsx(
            'flex items-center gap-1 px-3 py-1.5 font-mono text-[0.62rem] border rounded-sm transition-colors',
            step === 1
              ? 'border-border-subtle text-text-muted opacity-40 cursor-not-allowed'
              : 'border-border-subtle text-text-secondary hover:text-text-primary'
          )}
          aria-label="Previous step"
        >
          <ChevronLeft size={10} />
          BACK
        </button>
        <div className="flex-1 flex items-center justify-center gap-1">
          {STEPS.map(s => (
            <div
              key={s.n}
              className={clsx(
                'w-1.5 h-1.5 rounded-full transition-colors',
                step === s.n ? 'bg-accent-cyan' : step > s.n ? 'bg-positive' : 'bg-border-subtle'
              )}
            />
          ))}
        </div>
        {step < 4 ? (
          <button
            onClick={handleNext}
            disabled={!canProceed[step]}
            className={clsx(
              'flex items-center gap-1 px-3 py-1.5 font-mono text-[0.62rem] border rounded-sm transition-colors',
              canProceed[step]
                ? 'border-accent-cyan text-accent-cyan hover:bg-bg-panel-raised'
                : 'border-border-subtle text-text-muted opacity-40 cursor-not-allowed'
            )}
            aria-label="Next step"
          >
            NEXT
            <ChevronRight size={10} />
          </button>
        ) : (
          <button
            onClick={handleCreate}
            className="flex items-center gap-1 px-3 py-1.5 font-mono text-[0.62rem] border border-positive text-positive hover:bg-positive-bg rounded-sm transition-colors"
            aria-label="Confirm create agent"
          >
            <Check size={10} />
            CREATE AGENT
          </button>
        )}
      </div>
    </div>
  )
}

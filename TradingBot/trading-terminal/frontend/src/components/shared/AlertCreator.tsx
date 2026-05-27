import React, { useState } from 'react'
import clsx from 'clsx'
import { Bell, BellOff, Trash2 } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiDelete } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ─────────────────────────────────────────────────────────────────────

type AlertType = 'PRICE' | 'PERCENT_CHANGE' | 'VOLUME' | 'SIGNAL'
type AlertStatus = 'ACTIVE' | 'TRIGGERED'
type PriceCondition = 'ABOVE' | 'BELOW' | 'CROSSES'
type Notification = 'IN_APP' | 'SOUND' | 'BOTH'
type Timeframe = '1m' | '5m' | '1h' | '1d'
type SignalDirection = 'LONG' | 'SHORT' | 'ANY'

interface PriceAlertConfig {
  symbol: string
  condition: PriceCondition
  price: string
  notification: Notification
}

interface PercentChangeAlertConfig {
  symbol: string
  threshold: string
  timeframe: Timeframe
}

interface VolumeAlertConfig {
  symbol: string
  multiplier: string
}

interface SignalAlertConfig {
  source: string
  direction: SignalDirection
  confidenceThreshold: string
}

interface Alert {
  id: string
  type: AlertType
  description: string
  status: AlertStatus
  createdAt: number
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildDescription(type: AlertType, config: PriceAlertConfig | PercentChangeAlertConfig | VolumeAlertConfig | SignalAlertConfig): string {
  switch (type) {
    case 'PRICE': {
      const c = config as PriceAlertConfig
      return `${c.symbol} ${c.condition} $${c.price}`
    }
    case 'PERCENT_CHANGE': {
      const c = config as PercentChangeAlertConfig
      return `${c.symbol} ${c.threshold}% change in ${c.timeframe}`
    }
    case 'VOLUME': {
      const c = config as VolumeAlertConfig
      return `${c.symbol} volume spike ${c.multiplier}x`
    }
    case 'SIGNAL': {
      const c = config as SignalAlertConfig
      return `${c.source} ${c.direction} signal ≥${c.confidenceThreshold}%`
    }
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
      {children}
    </label>
  )
}

function SegControl<T extends string>({
  options,
  value,
  onChange,
  labelFn,
}: {
  options: T[]
  value: T
  onChange: (v: T) => void
  labelFn?: (v: T) => string
}) {
  return (
    <div className="flex border border-border-subtle rounded-sm overflow-hidden">
      {options.map(opt => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          className={clsx(
            'flex-1 py-1 font-mono text-[0.55rem] uppercase tracking-wide transition-colors border-r border-border-subtle last:border-r-0',
            opt === value
              ? 'bg-bg-panel-raised text-accent-cyan'
              : 'bg-bg-panel text-text-muted hover:text-text-secondary',
          )}
        >
          {labelFn ? labelFn(opt) : opt}
        </button>
      ))}
    </div>
  )
}

// ── Alert form panes ──────────────────────────────────────────────────────────

function PriceAlertForm({
  config,
  onChange,
}: {
  config: PriceAlertConfig
  onChange: (p: Partial<PriceAlertConfig>) => void
}) {
  return (
    <div className="space-y-2">
      <div>
        <Label>Symbol</Label>
        <input
          type="text"
          value={config.symbol}
          onChange={e => onChange({ symbol: e.target.value.toUpperCase() })}
          placeholder="AAPL"
          className="terminal-input h-7 text-sm uppercase font-semibold text-accent-cyan"
        />
      </div>
      <div>
        <Label>Condition</Label>
        <SegControl<PriceCondition>
          options={['ABOVE', 'BELOW', 'CROSSES']}
          value={config.condition}
          onChange={v => onChange({ condition: v })}
        />
      </div>
      <div>
        <Label>Price ($)</Label>
        <input
          type="number"
          step="0.01"
          min="0"
          value={config.price}
          onChange={e => onChange({ price: e.target.value })}
          placeholder="0.00"
          className="terminal-input h-7 tabular-nums"
        />
      </div>
      <div>
        <Label>Notification</Label>
        <SegControl<Notification>
          options={['IN_APP', 'SOUND', 'BOTH']}
          value={config.notification}
          onChange={v => onChange({ notification: v })}
          labelFn={v => v === 'IN_APP' ? 'In-App' : v === 'SOUND' ? 'Sound' : 'Both'}
        />
      </div>
    </div>
  )
}

function PercentChangeForm({
  config,
  onChange,
}: {
  config: PercentChangeAlertConfig
  onChange: (p: Partial<PercentChangeAlertConfig>) => void
}) {
  return (
    <div className="space-y-2">
      <div>
        <Label>Symbol</Label>
        <input
          type="text"
          value={config.symbol}
          onChange={e => onChange({ symbol: e.target.value.toUpperCase() })}
          placeholder="TSLA"
          className="terminal-input h-7 text-sm uppercase font-semibold text-accent-cyan"
        />
      </div>
      <div>
        <Label>Threshold %</Label>
        <input
          type="number"
          step="0.5"
          value={config.threshold}
          onChange={e => onChange({ threshold: e.target.value })}
          placeholder="5.0"
          className="terminal-input h-7 tabular-nums"
        />
      </div>
      <div>
        <Label>Timeframe</Label>
        <SegControl<Timeframe>
          options={['1m', '5m', '1h', '1d']}
          value={config.timeframe}
          onChange={v => onChange({ timeframe: v })}
        />
      </div>
    </div>
  )
}

function VolumeAlertForm({
  config,
  onChange,
}: {
  config: VolumeAlertConfig
  onChange: (p: Partial<VolumeAlertConfig>) => void
}) {
  return (
    <div className="space-y-2">
      <div>
        <Label>Symbol</Label>
        <input
          type="text"
          value={config.symbol}
          onChange={e => onChange({ symbol: e.target.value.toUpperCase() })}
          placeholder="SPY"
          className="terminal-input h-7 text-sm uppercase font-semibold text-accent-cyan"
        />
      </div>
      <div>
        <Label>Volume Spike Multiplier (x)</Label>
        <input
          type="number"
          step="0.5"
          min="1.5"
          value={config.multiplier}
          onChange={e => onChange({ multiplier: e.target.value })}
          placeholder="3.0"
          className="terminal-input h-7 tabular-nums"
        />
        <p className="font-mono text-[0.5rem] text-text-muted mt-0.5">
          Trigger when volume exceeds {config.multiplier || '3'}x 20-period average
        </p>
      </div>
    </div>
  )
}

function SignalAlertForm({
  config,
  onChange,
}: {
  config: SignalAlertConfig
  onChange: (p: Partial<SignalAlertConfig>) => void
}) {
  return (
    <div className="space-y-2">
      <div>
        <Label>Signal Source</Label>
        <input
          type="text"
          value={config.source}
          onChange={e => onChange({ source: e.target.value })}
          placeholder="MomentumAgent"
          className="terminal-input h-7 text-sm text-accent-cyan"
        />
      </div>
      <div>
        <Label>Direction</Label>
        <SegControl<SignalDirection>
          options={['LONG', 'SHORT', 'ANY']}
          value={config.direction}
          onChange={v => onChange({ direction: v })}
        />
      </div>
      <div>
        <Label>Confidence Threshold (%)</Label>
        <input
          type="number"
          step="1"
          min="0"
          max="100"
          value={config.confidenceThreshold}
          onChange={e => onChange({ confidenceThreshold: e.target.value })}
          placeholder="70"
          className="terminal-input h-7 tabular-nums"
        />
      </div>
    </div>
  )
}

// ── Active alerts list ────────────────────────────────────────────────────────

function AlertRow({ alert, onDelete }: { alert: Alert; onDelete: (id: string) => void }) {
  const triggered = alert.status === 'TRIGGERED'
  return (
    <div className={clsx(
      'flex items-center gap-2 px-2.5 py-1.5 border-b border-border-muted last:border-0',
      triggered ? 'bg-warning-bg' : '',
    )}>
      {triggered
        ? <Bell size={9} className="text-warning flex-shrink-0" />
        : <Bell size={9} className="text-positive flex-shrink-0" />
      }
      <div className="flex-1 min-w-0">
        <p className="font-mono text-[0.6rem] text-text-primary truncate">{alert.description}</p>
        <p className="font-mono text-[0.5rem] text-text-muted">
          {alert.type} · {new Date(alert.createdAt).toLocaleTimeString('en-US', { hour12: false })}
        </p>
      </div>
      <span className={clsx(
        'font-mono text-[0.5rem] uppercase font-semibold px-1 py-0.5 rounded-sm',
        triggered ? 'text-warning bg-warning-bg border border-warning' : 'text-positive bg-positive-bg border border-positive',
      )}>
        {alert.status}
      </span>
      <button
        type="button"
        onClick={() => onDelete(alert.id)}
        className="text-text-muted hover:text-negative transition-colors"
        aria-label={`Delete alert: ${alert.description}`}
      >
        <Trash2 size={9} />
      </button>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

const TABS: { id: AlertType; label: string }[] = [
  { id: 'PRICE', label: 'Price' },
  { id: 'PERCENT_CHANGE', label: '% Change' },
  { id: 'VOLUME', label: 'Volume' },
  { id: 'SIGNAL', label: 'Signal' },
]

export default function AlertCreator() {
  const [activeTab, setActiveTab] = useState<AlertType>('PRICE')
  const [saved, setSaved] = useState(false)
  const queryClient = useQueryClient()

  // Fetch alert rules from API
  const { data: rawAlerts = [] } = useQuery({
    queryKey: ['alert-rules'],
    queryFn: () => apiGet<any[]>(API.alertRules),
    placeholderData: [],
  })

  // Map API shape to component Alert shape
  const alerts: Alert[] = rawAlerts.map(r => ({
    id: r.rule_id ?? r.id ?? String(Math.random()),
    type: (r.type ?? 'PRICE') as AlertType,
    description: r.description ?? `${r.symbol ?? ''} ${r.condition ?? ''} ${r.threshold ?? ''}`.trim(),
    status: r.enabled ? 'ACTIVE' : ('TRIGGERED' as AlertStatus),
    createdAt: r.created_at ? new Date(r.created_at).getTime() : Date.now(),
  }))

  // Create mutation
  const createMutation = useMutation({
    mutationFn: (body: any) => apiPost<any>(API.alertRules, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['alert-rules'] }),
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete<any>(API.alertRule(id)),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['alert-rules'] }),
  })

  const [priceConfig, setPriceConfig] = useState<PriceAlertConfig>({
    symbol: '', condition: 'ABOVE', price: '', notification: 'BOTH',
  })
  const [pctConfig, setPctConfig] = useState<PercentChangeAlertConfig>({
    symbol: '', threshold: '5', timeframe: '1d',
  })
  const [volConfig, setVolConfig] = useState<VolumeAlertConfig>({
    symbol: '', multiplier: '3',
  })
  const [sigConfig, setSigConfig] = useState<SignalAlertConfig>({
    source: '', direction: 'LONG', confidenceThreshold: '70',
  })

  function handleSaveAlert() {
    const config = activeTab === 'PRICE' ? priceConfig
      : activeTab === 'PERCENT_CHANGE' ? pctConfig
      : activeTab === 'VOLUME' ? volConfig
      : sigConfig
    const description = buildDescription(activeTab, config)
    const body = {
      type: activeTab,
      description,
      ...(activeTab === 'PRICE' ? {
        symbol: (config as PriceAlertConfig).symbol,
        condition: (config as PriceAlertConfig).condition,
        threshold: parseFloat((config as PriceAlertConfig).price) || 0,
      } : activeTab === 'PERCENT_CHANGE' ? {
        symbol: (config as PercentChangeAlertConfig).symbol,
        condition: 'PERCENT_CHANGE',
        threshold: parseFloat((config as PercentChangeAlertConfig).threshold) || 0,
      } : activeTab === 'VOLUME' ? {
        symbol: (config as VolumeAlertConfig).symbol,
        condition: 'VOLUME_SPIKE',
        threshold: parseFloat((config as VolumeAlertConfig).multiplier) || 3,
      } : {
        source: (config as SignalAlertConfig).source,
        condition: 'SIGNAL',
        threshold: parseFloat((config as SignalAlertConfig).confidenceThreshold) || 70,
      }),
    }
    createMutation.mutate(body)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  function handleDelete(id: string) {
    deleteMutation.mutate(id)
  }

  const activeCount = alerts.filter(a => a.status === 'ACTIVE').length
  const triggeredCount = alerts.filter(a => a.status === 'TRIGGERED').length

  return (
    <div className="flex flex-col h-full">
      <div className="panel-header">
        <span className="flex-1">◈ Create Alert</span>
        <span className="font-mono text-[0.55rem] text-text-muted">
          {activeCount} active · {triggeredCount} triggered
        </span>
      </div>

      {/* Alert type tabs */}
      <div className="flex border-b border-border-subtle">
        {TABS.map(tab => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={clsx(
              'flex-1 py-1.5 font-mono text-[0.55rem] uppercase tracking-wide transition-colors',
              activeTab === tab.id
                ? 'text-accent-cyan border-b border-accent-cyan bg-bg-panel-raised'
                : 'text-text-muted hover:text-text-secondary',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="px-2.5 pt-2 space-y-2 flex-1 overflow-y-auto">
        {activeTab === 'PRICE' && (
          <PriceAlertForm config={priceConfig} onChange={p => setPriceConfig(c => ({ ...c, ...p }))} />
        )}
        {activeTab === 'PERCENT_CHANGE' && (
          <PercentChangeForm config={pctConfig} onChange={p => setPctConfig(c => ({ ...c, ...p }))} />
        )}
        {activeTab === 'VOLUME' && (
          <VolumeAlertForm config={volConfig} onChange={p => setVolConfig(c => ({ ...c, ...p }))} />
        )}
        {activeTab === 'SIGNAL' && (
          <SignalAlertForm config={sigConfig} onChange={p => setSigConfig(c => ({ ...c, ...p }))} />
        )}

        <button
          type="button"
          onClick={handleSaveAlert}
          className={clsx(
            'w-full py-1.5 font-mono text-[0.68rem] font-bold uppercase tracking-wider rounded-sm border transition-colors',
            saved
              ? 'bg-positive border-positive text-bg-root'
              : 'bg-bg-panel-raised border-accent-cyan text-accent-cyan hover:bg-bg-panel',
          )}
        >
          {saved ? '✓ Alert Saved' : 'Save Alert'}
        </button>

        {/* Active alerts list */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">Active Alerts</span>
            {triggeredCount > 0 && (
              <span className="font-mono text-[0.5rem] text-warning font-semibold">
                {triggeredCount} triggered
              </span>
            )}
          </div>

          {alerts.length === 0 ? (
            <div className="flex items-center gap-2 py-4 justify-center">
              <BellOff size={12} className="text-text-muted" />
              <span className="font-mono text-[0.62rem] text-text-muted">No alerts configured</span>
            </div>
          ) : (
            <div className="border border-border-subtle rounded-sm overflow-hidden">
              {alerts.map(alert => (
                <AlertRow key={alert.id} alert={alert} onDelete={handleDelete} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

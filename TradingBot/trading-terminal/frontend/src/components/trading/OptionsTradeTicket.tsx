import React, { useState, useCallback } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Inline types ─────────────────────────────────────────────────────────────

export type OptionsOrderType = 'LIMIT' | 'MARKET' | 'CREDIT' | 'DEBIT'
export type OptionsSide = 'BUY' | 'SELL'
export type OptionRight = 'CALL' | 'PUT'
export type OptionsAction = 'OPEN_LONG' | 'OPEN_SHORT' | 'CLOSE'
export type OptionsTab = 'SINGLE' | 'SPREAD' | 'IRON_CONDOR' | 'CUSTOM'

export interface OptionsLeg {
  expiry: string
  strike: number
  right: OptionRight
  side: OptionsSide
  quantity: number
  limitPrice?: number
}

export interface OptionsOrderRequest {
  symbol: string
  strategy: OptionsTab
  legs: OptionsLeg[]
  orderType: OptionsOrderType
  limitPrice?: number
  action: OptionsAction
  notes?: string
}

interface RiskSummary {
  maxProfit: number | null
  maxLoss: number | null
  breakevens: number[]
  roi: number | null
  probabilityOfProfit: number
}

interface OptionsTradeTicketProps {
  defaultSymbol?: string
  onSubmit?: (order: OptionsOrderRequest) => Promise<void>
}

// ── Mock data helpers ─────────────────────────────────────────────────────────

function mockStrikes(basePrice = 185): number[] {
  const strikes: number[] = []
  for (let i = -10; i <= 10; i++) {
    strikes.push(Math.round((basePrice + i * 5) * 100) / 100)
  }
  return strikes
}

function strikeLabel(strike: number, atm = 185): string {
  const diff = strike - atm
  if (Math.abs(diff) < 2.5) return 'ATM'
  return diff > 0 ? `OTM+${Math.abs(diff).toFixed(0)}` : `ITM+${Math.abs(diff).toFixed(0)}`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
      {children}
    </label>
  )
}

function FieldGroup({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={clsx('space-y-0.5', className)}>{children}</div>
}

function SegControl<T extends string>({
  options,
  value,
  onChange,
  colorFn,
}: {
  options: T[]
  value: T
  onChange: (v: T) => void
  colorFn?: (v: T, active: boolean) => string
}) {
  return (
    <div className="flex border border-border-subtle rounded-sm overflow-hidden">
      {options.map(opt => {
        const active = opt === value
        const extra = colorFn?.(opt, active) ?? ''
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={clsx(
              'flex-1 py-1.5 font-mono text-[0.6rem] font-semibold uppercase tracking-wide transition-colors border-r border-border-subtle last:border-r-0',
              active
                ? extra || 'bg-bg-panel-raised text-accent-cyan'
                : 'bg-bg-panel text-text-muted hover:text-text-secondary',
            )}
          >
            {opt}
          </button>
        )
      })}
    </div>
  )
}

function RiskSummaryRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex justify-between items-center py-0.5">
      <span className="font-mono text-[0.55rem] text-text-muted">{label}</span>
      <span className={clsx('font-mono text-[0.65rem] tabular-nums font-medium', color ?? 'text-text-primary')}>
        {value}
      </span>
    </div>
  )
}

// ── Single Leg Form ───────────────────────────────────────────────────────────

interface SingleLegState {
  symbol: string
  expiry: string
  strike: number
  right: OptionRight
  side: OptionsSide
  quantity: string
  orderType: OptionsOrderType
  limitPrice: string
}

function SingleLegForm({
  state,
  onChange,
  expiries,
}: {
  state: SingleLegState
  onChange: (partial: Partial<SingleLegState>) => void
  expiries: string[]
}) {
  const strikes = mockStrikes(185)
  return (
    <div className="space-y-2">
      <FieldGroup>
        <Label>Symbol</Label>
        <input
          type="text"
          value={state.symbol}
          onChange={e => onChange({ symbol: e.target.value.toUpperCase() })}
          placeholder="AAPL"
          className="terminal-input h-7 text-sm uppercase font-semibold text-accent-cyan"
        />
      </FieldGroup>

      <FieldGroup>
        <Label>Expiry</Label>
        <select
          value={state.expiry}
          onChange={e => onChange({ expiry: e.target.value })}
          className="terminal-input h-7 text-xs"
        >
          {expiries.map(exp => (
            <option key={exp} value={exp}>{exp}</option>
          ))}
        </select>
      </FieldGroup>

      <FieldGroup>
        <Label>Strike</Label>
        <select
          value={state.strike}
          onChange={e => onChange({ strike: Number(e.target.value) })}
          className="terminal-input h-7 text-xs"
        >
          {strikes.map(s => (
            <option key={s} value={s}>{s} ({strikeLabel(s)})</option>
          ))}
        </select>
      </FieldGroup>

      <FieldGroup>
        <Label>Right</Label>
        <SegControl<OptionRight>
          options={['CALL', 'PUT']}
          value={state.right}
          onChange={v => onChange({ right: v })}
          colorFn={(v, active) =>
            active
              ? v === 'CALL' ? 'bg-positive-bg text-positive border-positive' : 'bg-negative-bg text-negative border-negative'
              : ''
          }
        />
      </FieldGroup>

      <FieldGroup>
        <Label>Side</Label>
        <SegControl<OptionsSide>
          options={['BUY', 'SELL']}
          value={state.side}
          onChange={v => onChange({ side: v })}
          colorFn={(v, active) =>
            active
              ? v === 'BUY' ? 'bg-positive text-bg-root' : 'bg-negative text-white'
              : ''
          }
        />
      </FieldGroup>

      <FieldGroup>
        <Label>Qty (Contracts)</Label>
        <input
          type="number"
          min="1"
          step="1"
          value={state.quantity}
          onChange={e => onChange({ quantity: e.target.value })}
          placeholder="1"
          className="terminal-input h-7 tabular-nums"
        />
      </FieldGroup>

      <FieldGroup>
        <Label>Order Type</Label>
        <div className="flex gap-0.5">
          {(['LIMIT', 'MARKET', 'CREDIT', 'DEBIT'] as OptionsOrderType[]).map(t => (
            <button
              key={t}
              type="button"
              onClick={() => onChange({ orderType: t })}
              className={clsx(
                'flex-1 py-1 font-mono text-[0.5rem] uppercase tracking-wide border rounded-sm transition-colors',
                state.orderType === t
                  ? 'bg-bg-panel-raised border-accent-cyan text-accent-cyan'
                  : 'border-border-subtle text-text-muted hover:border-accent-cyan',
              )}
            >
              {t}
            </button>
          ))}
        </div>
      </FieldGroup>

      {(state.orderType === 'LIMIT' || state.orderType === 'CREDIT' || state.orderType === 'DEBIT') && (
        <FieldGroup>
          <Label>Limit / Net Price</Label>
          <input
            type="number"
            step="0.01"
            min="0"
            value={state.limitPrice}
            onChange={e => onChange({ limitPrice: e.target.value })}
            placeholder="0.00"
            className="terminal-input h-7 tabular-nums"
          />
        </FieldGroup>
      )}
    </div>
  )
}

// ── Spread Form ───────────────────────────────────────────────────────────────

interface SpreadLegState {
  expiry: string
  strike: number
  right: OptionRight
}

interface SpreadState {
  symbol: string
  long: SpreadLegState
  short: SpreadLegState
  limitPrice: string
}

function SpreadForm({
  state,
  onChange,
  expiries,
}: {
  state: SpreadState
  onChange: (partial: Partial<SpreadState>) => void
  expiries: string[]
}) {
  const strikes = mockStrikes(185)
  const netDebit = Number(state.limitPrice) || 0
  const isCredit = netDebit < 0

  function LegSection({
    title,
    leg,
    onLegChange,
  }: {
    title: string
    leg: SpreadLegState
    onLegChange: (partial: Partial<SpreadLegState>) => void
  }) {
    return (
      <div className="p-2 bg-bg-root border border-border-subtle rounded-sm space-y-1.5">
        <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">{title}</p>
        <div className="grid grid-cols-2 gap-1">
          <div>
            <Label>Expiry</Label>
            <select
              value={leg.expiry}
              onChange={e => onLegChange({ expiry: e.target.value })}
              className="terminal-input h-6 text-[0.6rem]"
            >
              {expiries.map(exp => <option key={exp} value={exp}>{exp}</option>)}
            </select>
          </div>
          <div>
            <Label>Right</Label>
            <select
              value={leg.right}
              onChange={e => onLegChange({ right: e.target.value as OptionRight })}
              className="terminal-input h-6 text-[0.6rem]"
            >
              <option value="CALL">CALL</option>
              <option value="PUT">PUT</option>
            </select>
          </div>
        </div>
        <div>
          <Label>Strike</Label>
          <select
            value={leg.strike}
            onChange={e => onLegChange({ strike: Number(e.target.value) })}
            className="terminal-input h-6 text-[0.6rem]"
          >
            {strikes.map(s => <option key={s} value={s}>{s} ({strikeLabel(s)})</option>)}
          </select>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <FieldGroup>
        <Label>Symbol</Label>
        <input
          type="text"
          value={state.symbol}
          onChange={e => onChange({ symbol: e.target.value.toUpperCase() })}
          placeholder="AAPL"
          className="terminal-input h-7 text-sm uppercase font-semibold text-accent-cyan"
        />
      </FieldGroup>

      <LegSection
        title="Long Leg"
        leg={state.long}
        onLegChange={partial => onChange({ long: { ...state.long, ...partial } })}
      />
      <LegSection
        title="Short Leg"
        leg={state.short}
        onLegChange={partial => onChange({ short: { ...state.short, ...partial } })}
      />

      <FieldGroup>
        <Label>Net {isCredit ? 'Credit' : 'Debit'} Price</Label>
        <input
          type="number"
          step="0.01"
          value={state.limitPrice}
          onChange={e => onChange({ limitPrice: e.target.value })}
          placeholder="0.00"
          className="terminal-input h-7 tabular-nums"
        />
        <p className="font-mono text-[0.55rem] text-text-muted mt-0.5">
          Negative = credit, Positive = debit
        </p>
      </FieldGroup>
    </div>
  )
}

// ── Iron Condor Form ──────────────────────────────────────────────────────────

interface IronCondorState {
  symbol: string
  expiry: string
  atmPrice: number
  callShortWidth: number
  callLongWidth: number
  putShortWidth: number
  putLongWidth: number
  credit: string
}

function IronCondorForm({
  state,
  onChange,
  expiries,
}: {
  state: IronCondorState
  onChange: (partial: Partial<IronCondorState>) => void
  expiries: string[]
}) {
  const shortCall = state.atmPrice + state.callShortWidth
  const longCall = state.atmPrice + state.callShortWidth + state.callLongWidth
  const shortPut = state.atmPrice - state.putShortWidth
  const longPut = state.atmPrice - state.putShortWidth - state.putLongWidth
  const credit = Number(state.credit) || 0
  const maxProfit = credit * 100
  const maxLoss = (Math.min(state.callLongWidth, state.putLongWidth) - credit) * 100
  const upperBreakeven = shortCall + credit
  const lowerBreakeven = shortPut - credit

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-1">
        <FieldGroup>
          <Label>Symbol</Label>
          <input
            type="text"
            value={state.symbol}
            onChange={e => onChange({ symbol: e.target.value.toUpperCase() })}
            placeholder="AAPL"
            className="terminal-input h-7 text-sm uppercase font-semibold text-accent-cyan"
          />
        </FieldGroup>
        <FieldGroup>
          <Label>Expiry</Label>
          <select
            value={state.expiry}
            onChange={e => onChange({ expiry: e.target.value })}
            className="terminal-input h-7 text-xs"
          >
            {expiries.map(exp => <option key={exp} value={exp}>{exp}</option>)}
          </select>
        </FieldGroup>
      </div>

      <FieldGroup>
        <Label>Underlying Price (ATM)</Label>
        <input
          type="number"
          step="0.01"
          value={state.atmPrice}
          onChange={e => onChange({ atmPrice: Number(e.target.value) })}
          className="terminal-input h-7 tabular-nums"
        />
      </FieldGroup>

      <div className="grid grid-cols-2 gap-1">
        <FieldGroup>
          <Label>Call Short Width</Label>
          <input type="number" step="1" min="1" value={state.callShortWidth}
            onChange={e => onChange({ callShortWidth: Number(e.target.value) })}
            className="terminal-input h-7 tabular-nums" />
        </FieldGroup>
        <FieldGroup>
          <Label>Call Long Width</Label>
          <input type="number" step="1" min="1" value={state.callLongWidth}
            onChange={e => onChange({ callLongWidth: Number(e.target.value) })}
            className="terminal-input h-7 tabular-nums" />
        </FieldGroup>
        <FieldGroup>
          <Label>Put Short Width</Label>
          <input type="number" step="1" min="1" value={state.putShortWidth}
            onChange={e => onChange({ putShortWidth: Number(e.target.value) })}
            className="terminal-input h-7 tabular-nums" />
        </FieldGroup>
        <FieldGroup>
          <Label>Put Long Width</Label>
          <input type="number" step="1" min="1" value={state.putLongWidth}
            onChange={e => onChange({ putLongWidth: Number(e.target.value) })}
            className="terminal-input h-7 tabular-nums" />
        </FieldGroup>
      </div>

      <FieldGroup>
        <Label>Net Credit / Contract</Label>
        <input type="number" step="0.01" min="0" value={state.credit}
          onChange={e => onChange({ credit: e.target.value })}
          placeholder="2.50"
          className="terminal-input h-7 tabular-nums" />
      </FieldGroup>

      {/* Auto-configured legs display */}
      <div className="p-2 bg-bg-root border border-border-subtle rounded-sm">
        <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1.5">Auto-Configured Legs</p>
        <div className="space-y-1">
          {[
            { leg: 'Sell Call', strike: shortCall, color: 'text-negative' },
            { leg: 'Buy Call', strike: longCall, color: 'text-positive' },
            { leg: 'Sell Put', strike: shortPut, color: 'text-negative' },
            { leg: 'Buy Put', strike: longPut, color: 'text-positive' },
          ].map(({ leg, strike, color }) => (
            <div key={leg} className="flex justify-between">
              <span className={clsx('font-mono text-[0.6rem]', color)}>{leg}</span>
              <span className="font-mono text-[0.65rem] tabular-nums text-text-primary">${strike.toFixed(2)}</span>
            </div>
          ))}
        </div>
        <div className="mt-2 pt-1.5 border-t border-border-subtle space-y-0.5">
          <div className="flex justify-between">
            <span className="font-mono text-[0.55rem] text-text-muted">Max Profit</span>
            <span className="font-mono text-[0.65rem] text-positive tabular-nums">${maxProfit.toFixed(0)}</span>
          </div>
          <div className="flex justify-between">
            <span className="font-mono text-[0.55rem] text-text-muted">Max Loss</span>
            <span className="font-mono text-[0.65rem] text-negative tabular-nums">${maxLoss.toFixed(0)}</span>
          </div>
          <div className="flex justify-between">
            <span className="font-mono text-[0.55rem] text-text-muted">Breakevens</span>
            <span className="font-mono text-[0.65rem] tabular-nums text-warning">
              ${lowerBreakeven.toFixed(2)} / ${upperBreakeven.toFixed(2)}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Risk Summary Component ────────────────────────────────────────────────────

function RiskSummaryPanel({ summary }: { summary: RiskSummary }) {
  return (
    <div className="mx-0 mt-2 p-2 bg-bg-root border border-border-subtle rounded-sm">
      <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1">Risk Summary</p>
      <RiskSummaryRow
        label="Max Profit"
        value={summary.maxProfit !== null ? `$${summary.maxProfit.toFixed(0)}` : 'Unlimited'}
        color={summary.maxProfit !== null ? 'text-positive' : 'text-accent-amber'}
      />
      <RiskSummaryRow
        label="Max Loss"
        value={summary.maxLoss !== null ? `$${summary.maxLoss.toFixed(0)}` : 'Unlimited'}
        color={summary.maxLoss !== null ? 'text-negative' : 'text-accent-amber'}
      />
      <RiskSummaryRow
        label="Breakeven(s)"
        value={summary.breakevens.length > 0 ? summary.breakevens.map(b => `$${b.toFixed(2)}`).join(' / ') : '—'}
        color="text-warning"
      />
      <RiskSummaryRow
        label="ROI%"
        value={summary.roi !== null ? `${summary.roi.toFixed(1)}%` : '—'}
        color={summary.roi !== null && summary.roi > 0 ? 'text-positive' : 'text-text-primary'}
      />
      <RiskSummaryRow
        label="Prob. of Profit"
        value={`${summary.probabilityOfProfit.toFixed(0)}%`}
        color={summary.probabilityOfProfit > 50 ? 'text-positive' : 'text-warning'}
      />
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

const TABS: { id: OptionsTab; label: string }[] = [
  { id: 'SINGLE', label: 'Single Leg' },
  { id: 'SPREAD', label: 'Spread' },
  { id: 'IRON_CONDOR', label: 'Iron Condor' },
  { id: 'CUSTOM', label: 'Custom' },
]

const DEFAULT_SINGLE: SingleLegState = {
  symbol: '',
  expiry: '',
  strike: 185,
  right: 'CALL',
  side: 'BUY',
  quantity: '1',
  orderType: 'LIMIT',
  limitPrice: '',
}

const DEFAULT_SPREAD: SpreadState = {
  symbol: '',
  long: { expiry: '', strike: 185, right: 'CALL' },
  short: { expiry: '', strike: 190, right: 'CALL' },
  limitPrice: '',
}

const DEFAULT_CONDOR: IronCondorState = {
  symbol: '',
  expiry: '',
  atmPrice: 185,
  callShortWidth: 5,
  callLongWidth: 5,
  putShortWidth: 5,
  putLongWidth: 5,
  credit: '2.50',
}

function computeSingleRisk(state: SingleLegState): RiskSummary {
  const price = Number(state.limitPrice) || 2
  const qty = Number(state.quantity) || 1
  const totalPremium = price * qty * 100
  if (state.side === 'BUY') {
    return {
      maxProfit: state.right === 'CALL' ? null : totalPremium,
      maxLoss: totalPremium,
      breakevens: [state.right === 'CALL' ? state.strike + price : state.strike - price],
      roi: null,
      probabilityOfProfit: 45,
    }
  }
  return {
    maxProfit: totalPremium,
    maxLoss: state.right === 'CALL' ? null : totalPremium,
    breakevens: [state.right === 'CALL' ? state.strike + price : state.strike - price],
    roi: ((totalPremium) / (state.strike * qty * 100)) * 100,
    probabilityOfProfit: 55,
  }
}

function computeSpreadRisk(state: SpreadState): RiskSummary {
  const debit = Number(state.limitPrice) || 0
  const width = Math.abs(state.long.strike - state.short.strike)
  return {
    maxProfit: debit < 0 ? Math.abs(debit) * 100 : (width - debit) * 100,
    maxLoss: debit > 0 ? debit * 100 : (width + debit) * 100,
    breakevens: [state.long.strike + Math.abs(debit)],
    roi: debit > 0 ? ((width - debit) / debit) * 100 : null,
    probabilityOfProfit: 50,
  }
}

function computeCondorRisk(state: IronCondorState): RiskSummary {
  const credit = Number(state.credit) || 0
  const width = Math.min(state.callLongWidth, state.putLongWidth)
  return {
    maxProfit: credit * 100,
    maxLoss: (width - credit) * 100,
    breakevens: [
      state.atmPrice - state.putShortWidth - credit,
      state.atmPrice + state.callShortWidth + credit,
    ],
    roi: credit > 0 ? (credit / (width - credit)) * 100 : null,
    probabilityOfProfit: 65,
  }
}

export default function OptionsTradeTicket({ defaultSymbol = '', onSubmit }: OptionsTradeTicketProps) {
  const [activeTab, setActiveTab] = useState<OptionsTab>('SINGLE')
  const [single, setSingle] = useState<SingleLegState>({ ...DEFAULT_SINGLE, symbol: defaultSymbol })
  const [spread, setSpread] = useState<SpreadState>({ ...DEFAULT_SPREAD, symbol: defaultSymbol })
  const [condor, setCondor] = useState<IronCondorState>({ ...DEFAULT_CONDOR, symbol: defaultSymbol })
  const [action, setAction] = useState<OptionsAction>('OPEN_LONG')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')

  const currentSymbol = activeTab === 'SINGLE' ? single.symbol : activeTab === 'SPREAD' ? spread.symbol : condor.symbol

  const { data: expiries = [] } = useQuery({
    queryKey: ['options-expiries', currentSymbol],
    queryFn: () => apiGet<string[]>(API.optionsExpiries(currentSymbol)),
    enabled: !!currentSymbol,
    staleTime: 300_000,
    placeholderData: [],
  })

  const riskSummary: RiskSummary = useCallback(() => {
    if (activeTab === 'SINGLE') return computeSingleRisk(single)
    if (activeTab === 'SPREAD') return computeSpreadRisk(spread)
    if (activeTab === 'IRON_CONDOR') return computeCondorRisk(condor)
    return { maxProfit: null, maxLoss: null, breakevens: [], roi: null, probabilityOfProfit: 50 }
  }, [activeTab, single, spread, condor])()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const order = buildOrder()
      await onSubmit?.(order)
      setSubmitted(true)
      setTimeout(() => setSubmitted(false), 2000)
    } catch {
      setError('Submission failed. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  function buildOrder(): OptionsOrderRequest {
    if (activeTab === 'SINGLE') {
      return {
        symbol: single.symbol,
        strategy: 'SINGLE',
        legs: [{
          expiry: single.expiry,
          strike: single.strike,
          right: single.right,
          side: single.side,
          quantity: Number(single.quantity),
          limitPrice: single.limitPrice ? Number(single.limitPrice) : undefined,
        }],
        orderType: single.orderType,
        limitPrice: single.limitPrice ? Number(single.limitPrice) : undefined,
        action,
      }
    }
    if (activeTab === 'SPREAD') {
      return {
        symbol: spread.symbol,
        strategy: 'SPREAD',
        legs: [
          { expiry: spread.long.expiry, strike: spread.long.strike, right: spread.long.right, side: 'BUY', quantity: 1 },
          { expiry: spread.short.expiry, strike: spread.short.strike, right: spread.short.right, side: 'SELL', quantity: 1 },
        ],
        orderType: Number(spread.limitPrice) < 0 ? 'CREDIT' : 'DEBIT',
        limitPrice: Math.abs(Number(spread.limitPrice)),
        action,
      }
    }
    return {
      symbol: condor.symbol,
      strategy: 'IRON_CONDOR',
      legs: [
        { expiry: condor.expiry, strike: condor.atmPrice + condor.callShortWidth, right: 'CALL', side: 'SELL', quantity: 1 },
        { expiry: condor.expiry, strike: condor.atmPrice + condor.callShortWidth + condor.callLongWidth, right: 'CALL', side: 'BUY', quantity: 1 },
        { expiry: condor.expiry, strike: condor.atmPrice - condor.putShortWidth, right: 'PUT', side: 'SELL', quantity: 1 },
        { expiry: condor.expiry, strike: condor.atmPrice - condor.putShortWidth - condor.putLongWidth, right: 'PUT', side: 'BUY', quantity: 1 },
      ],
      orderType: 'CREDIT',
      limitPrice: Number(condor.credit),
      action,
    }
  }

  const actionButtonLabel = () => {
    if (submitted) return '✓ SUBMITTED'
    if (submitting) return 'SUBMITTING...'
    if (action === 'OPEN_LONG') return `OPEN LONG ${currentSymbol || '—'} ↵`
    if (action === 'OPEN_SHORT') return `OPEN SHORT ${currentSymbol || '—'} ↵`
    return `CLOSE ${currentSymbol || '—'} ↵`
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col">
      <div className="panel-header">
        <span className="flex-1">◈ Options Order Entry</span>
        {currentSymbol && (
          <span className="font-mono text-[0.65rem] text-accent-cyan font-semibold">{currentSymbol}</span>
        )}
      </div>

      {/* Tabs */}
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

      <div className="px-2.5 pt-2 space-y-2 overflow-y-auto flex-1">
        {activeTab === 'SINGLE' && (
          <SingleLegForm state={single} onChange={partial => setSingle(s => ({ ...s, ...partial }))} expiries={expiries} />
        )}
        {activeTab === 'SPREAD' && (
          <SpreadForm state={spread} onChange={partial => setSpread(s => ({ ...s, ...partial }))} expiries={expiries} />
        )}
        {activeTab === 'IRON_CONDOR' && (
          <IronCondorForm state={condor} onChange={partial => setCondor(s => ({ ...s, ...partial }))} expiries={expiries} />
        )}
        {activeTab === 'CUSTOM' && (
          <div className="py-8 text-center font-mono text-[0.65rem] text-text-muted">
            Custom multi-leg entry — use Spread Builder
          </div>
        )}

        <RiskSummaryPanel summary={riskSummary} />

        {/* Action selector */}
        <div>
          <Label>Action</Label>
          <div className="flex gap-0.5">
            {(['OPEN_LONG', 'OPEN_SHORT', 'CLOSE'] as OptionsAction[]).map(a => (
              <button
                key={a}
                type="button"
                onClick={() => setAction(a)}
                className={clsx(
                  'flex-1 py-1 font-mono text-[0.5rem] uppercase tracking-wide border rounded-sm transition-colors',
                  action === a
                    ? 'bg-bg-panel-raised border-accent-cyan text-accent-cyan'
                    : 'border-border-subtle text-text-muted hover:border-accent-cyan',
                )}
              >
                {a.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <p className="font-mono text-[0.6rem] text-negative px-2.5 mb-1">{error}</p>}

      <div className="px-2.5 pb-2.5 pt-2">
        <button
          type="submit"
          disabled={submitting || submitted}
          className={clsx(
            'w-full py-2 font-mono text-[0.72rem] font-bold uppercase tracking-wider rounded-sm border transition-colors',
            submitted
              ? 'bg-positive border-positive text-bg-root'
              : action === 'OPEN_LONG'
                ? 'bg-positive border-positive text-bg-root hover:bg-[#00c865] disabled:opacity-50'
                : action === 'OPEN_SHORT'
                  ? 'bg-negative border-negative text-white hover:bg-[#e01040] disabled:opacity-50'
                  : 'bg-bg-panel-raised border-accent-cyan text-accent-cyan hover:bg-bg-panel disabled:opacity-50',
          )}
        >
          {actionButtonLabel()}
        </button>
      </div>
    </form>
  )
}

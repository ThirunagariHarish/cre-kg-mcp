import React, { useState } from 'react'
import clsx from 'clsx'
import type { OrderRequest, OrderSide, OrderType, OrderTIF } from '@/types/orders'
import PreTradeRiskCheck from '@/components/risk/PreTradeRiskCheck'

interface RiskPreview {
  estimatedValue: number
  maxLoss?: number
  portfolioPercent?: number
  riskReward?: number
}

interface TradeTicketProps {
  defaultSymbol?: string
  availableCash?: number
  onSubmit: (order: OrderRequest) => Promise<void>
  riskPreview?: RiskPreview
  className?: string
}

const ORDER_TYPES: OrderType[] = ['MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT']
const TIFS: OrderTIF[] = ['DAY', 'GTC', 'IOC', 'FOK']

function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  getColor,
}: {
  options: T[]
  value: T
  onChange: (v: T) => void
  getColor?: (v: T, active: boolean) => string
}) {
  return (
    <div className="flex border border-border-subtle rounded-sm overflow-hidden">
      {options.map(opt => {
        const active = opt === value
        const extra = getColor?.(opt, active) ?? ''
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={clsx(
              'flex-1 py-1.5 font-mono text-[0.6rem] font-semibold uppercase tracking-wide transition-colors',
              active
                ? extra || 'bg-bg-panel-raised border-r border-border-subtle text-accent-cyan'
                : 'text-text-muted hover:text-text-secondary bg-bg-panel border-r border-border-subtle last:border-r-0',
              !active && 'last:border-r-0'
            )}
          >
            {opt}
          </button>
        )
      })}
    </div>
  )
}

export default function TradeTicket({
  defaultSymbol = '',
  availableCash,
  onSubmit,
  riskPreview,
  className,
}: TradeTicketProps) {
  const [symbol, setSymbol] = useState(defaultSymbol)
  const [side, setSide] = useState<OrderSide>('BUY')
  const [quantity, setQuantity] = useState('')
  const [orderType, setOrderType] = useState<OrderType>('MARKET')
  const [limitPrice, setLimitPrice] = useState('')
  const [stopPrice, setStopPrice] = useState('')
  const [tif, setTif] = useState<OrderTIF>('DAY')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [showRiskCheck, setShowRiskCheck] = useState(false)
  const [pendingOrder, setPendingOrder] = useState<OrderRequest | null>(null)

  const validate = (): boolean => {
    const errs: Record<string, string> = {}
    if (!symbol.trim()) errs.symbol = 'Required'
    if (!quantity || Number(quantity) <= 0) errs.quantity = 'Invalid'
    if ((orderType === 'LIMIT' || orderType === 'STOP_LIMIT') && !limitPrice) errs.limitPrice = 'Required'
    if ((orderType === 'STOP' || orderType === 'STOP_LIMIT') && !stopPrice) errs.stopPrice = 'Required'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    const order: OrderRequest = {
      symbol: symbol.toUpperCase().trim(),
      side,
      type: orderType,
      quantity: Number(quantity),
      limitPrice: limitPrice ? Number(limitPrice) : undefined,
      stopPrice: stopPrice ? Number(stopPrice) : undefined,
      timeInForce: tif,
    }
    setPendingOrder(order)
    setShowRiskCheck(true)
  }

  const handleRiskConfirm = async () => {
    if (!pendingOrder) return
    setShowRiskCheck(false)
    setSubmitting(true)
    try {
      await onSubmit(pendingOrder)
      setSubmitted(true)
      setTimeout(() => {
        setSubmitted(false)
        setSymbol(''); setQuantity(''); setLimitPrice(''); setStopPrice('')
      }, 2000)
    } catch {
      setErrors({ submit: 'Submission failed' })
    } finally {
      setSubmitting(false)
      setPendingOrder(null)
    }
  }

  const handleRiskCancel = () => {
    setShowRiskCheck(false)
    setPendingOrder(null)
  }

  const handleClear = () => {
    setSymbol(defaultSymbol); setQuantity(''); setLimitPrice(''); setStopPrice('')
    setErrors({}); setSide('BUY'); setOrderType('MARKET'); setTif('DAY')
  }

  const needsLimit = orderType === 'LIMIT' || orderType === 'STOP_LIMIT'
  const needsStop  = orderType === 'STOP' || orderType === 'STOP_LIMIT'
  const estVal = riskPreview?.estimatedValue ?? (Number(quantity) * (limitPrice ? Number(limitPrice) : 0))

  return (
    <form
      onSubmit={handleSubmit}
      onKeyDown={e => e.key === 'Escape' && handleClear()}
      className={clsx('flex flex-col', className)}
    >
      {/* Panel Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Order Entry</span>
        {symbol && <span className="font-mono text-[0.65rem] text-accent-cyan font-semibold">{symbol}</span>}
      </div>

      <div className="px-2.5 pt-2 space-y-2">
        {/* Symbol */}
        <div>
          <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
            Symbol
          </label>
          <input
            type="text"
            value={symbol}
            onChange={e => setSymbol(e.target.value.toUpperCase())}
            placeholder="AAPL"
            className={clsx('terminal-input h-7 text-sm uppercase font-semibold text-accent-cyan', errors.symbol && 'border-negative')}
            autoComplete="off"
          />
          {errors.symbol && <p className="font-mono text-[0.55rem] text-negative mt-0.5">{errors.symbol}</p>}
        </div>

        {/* BUY / SELL */}
        <div>
          <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
            Side
          </label>
          <div className="flex rounded-sm overflow-hidden border border-border-subtle">
            <button
              type="button"
              onClick={() => setSide('BUY')}
              className={clsx(
                'flex-1 py-2 font-mono text-[0.68rem] font-bold uppercase tracking-wider transition-colors',
                side === 'BUY'
                  ? 'bg-positive text-bg-root'
                  : 'bg-bg-panel text-text-muted hover:text-positive'
              )}
            >
              ▲ BUY
            </button>
            <button
              type="button"
              onClick={() => setSide('SELL')}
              className={clsx(
                'flex-1 py-2 font-mono text-[0.68rem] font-bold uppercase tracking-wider transition-colors border-l border-border-subtle',
                side === 'SELL'
                  ? 'bg-negative text-white'
                  : 'bg-bg-panel text-text-muted hover:text-negative'
              )}
            >
              ▼ SELL
            </button>
          </div>
        </div>

        {/* Qty */}
        <div>
          <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
            Quantity
          </label>
          <input
            type="number" min="1" step="1" value={quantity}
            onChange={e => setQuantity(e.target.value)}
            placeholder="100"
            className={clsx('terminal-input h-7 tabular-nums', errors.quantity && 'border-negative')}
          />
          {errors.quantity && <p className="font-mono text-[0.55rem] text-negative mt-0.5">{errors.quantity}</p>}
        </div>

        {/* Order Type */}
        <div>
          <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
            Order Type
          </label>
          <div className="flex gap-0.5">
            {ORDER_TYPES.map(t => (
              <button
                key={t} type="button" onClick={() => setOrderType(t)}
                className={clsx(
                  'flex-1 py-1 font-mono text-[0.55rem] uppercase tracking-wide border rounded-sm transition-colors',
                  orderType === t
                    ? 'bg-bg-panel-raised border-accent-cyan text-accent-cyan'
                    : 'border-border-subtle text-text-muted hover:border-accent-cyan hover:text-text-secondary'
                )}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Limit price */}
        {needsLimit && (
          <div>
            <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">Limit</label>
            <input
              type="number" step="0.01" min="0" value={limitPrice}
              onChange={e => setLimitPrice(e.target.value)}
              placeholder="0.00"
              className={clsx('terminal-input h-7 tabular-nums', errors.limitPrice && 'border-negative')}
            />
          </div>
        )}

        {/* Stop price */}
        {needsStop && (
          <div>
            <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">Stop</label>
            <input
              type="number" step="0.01" min="0" value={stopPrice}
              onChange={e => setStopPrice(e.target.value)}
              placeholder="0.00"
              className={clsx('terminal-input h-7 tabular-nums', errors.stopPrice && 'border-negative')}
            />
          </div>
        )}

        {/* TIF */}
        <div>
          <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
            Time in Force
          </label>
          <div className="flex gap-0.5">
            {TIFS.map(t => (
              <button
                key={t} type="button" onClick={() => setTif(t)}
                className={clsx(
                  'flex-1 py-1 font-mono text-[0.55rem] uppercase border rounded-sm transition-colors',
                  tif === t
                    ? 'bg-bg-panel-raised border-accent-cyan text-accent-cyan'
                    : 'border-border-subtle text-text-muted hover:border-border-subtle'
                )}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Risk Preview */}
      <div className="mx-2.5 my-2 p-2 bg-bg-root border border-border-subtle rounded-sm">
        <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1">
          Risk Preview
        </p>
        <div className="space-y-1">
          <div className="flex justify-between">
            <span className="font-mono text-[0.58rem] text-text-muted">Est. Value</span>
            <span className="font-mono text-[0.65rem] text-text-primary tabular-nums">
              {estVal > 0 ? `$${estVal.toLocaleString('en-US', { maximumFractionDigits: 0 })}` : '—'}
            </span>
          </div>
          {riskPreview?.portfolioPercent !== undefined && (
            <div className="flex justify-between">
              <span className="font-mono text-[0.58rem] text-text-muted">% Portfolio</span>
              <span className="font-mono text-[0.65rem] text-text-primary tabular-nums">{riskPreview.portfolioPercent.toFixed(1)}%</span>
            </div>
          )}
          {riskPreview?.maxLoss !== undefined && (
            <div className="flex justify-between">
              <span className="font-mono text-[0.58rem] text-text-muted">Max Loss</span>
              <span className="font-mono text-[0.65rem] text-negative tabular-nums">${riskPreview.maxLoss.toFixed(0)}</span>
            </div>
          )}
          {riskPreview?.riskReward !== undefined && (
            <div className="flex justify-between">
              <span className="font-mono text-[0.58rem] text-text-muted">R/R</span>
              <span className={clsx('font-mono text-[0.65rem] tabular-nums', riskPreview.riskReward >= 2 ? 'text-positive' : riskPreview.riskReward >= 1 ? 'text-warning' : 'text-negative')}>
                {riskPreview.riskReward.toFixed(1)}x
              </span>
            </div>
          )}
          {availableCash !== undefined && (
            <div className="flex justify-between border-t border-border-subtle pt-1 mt-1">
              <span className="font-mono text-[0.58rem] text-text-muted">Cash Avail.</span>
              <span className="font-mono text-[0.65rem] text-text-secondary tabular-nums">
                ${availableCash.toLocaleString('en-US', { maximumFractionDigits: 0 })}
              </span>
            </div>
          )}
        </div>
      </div>

      {errors.submit && (
        <p className="font-mono text-[0.6rem] text-negative px-2.5 mb-1">{errors.submit}</p>
      )}

      {/* Actions */}
      <div className="flex gap-1.5 px-2.5 pb-2.5">
        <button
          type="button"
          onClick={handleClear}
          className="flex-shrink-0 px-2.5 py-1.5 font-mono text-[0.6rem] text-text-muted border border-border-subtle rounded-sm hover:border-accent-cyan hover:text-text-secondary transition-colors"
        >
          CLR
        </button>
        <button
          type="submit"
          disabled={submitting || submitted}
          className={clsx(
            'flex-1 py-1.5 font-mono text-[0.72rem] font-bold uppercase tracking-wider rounded-sm border transition-colors',
            submitted
              ? 'bg-positive border-positive text-bg-root'
              : side === 'BUY'
                ? 'bg-positive border-positive text-bg-root hover:bg-[#00c865] disabled:opacity-50'
                : 'bg-negative border-negative text-white hover:bg-[#e01040] disabled:opacity-50'
          )}
        >
          {submitted ? '✓ SUBMITTED' : submitting ? 'SUBMITTING...' : `${side} ${symbol || '—'} ↵`}
        </button>
      </div>

      {/* Pre-trade risk check modal */}
      {showRiskCheck && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
          <div className="w-80 bg-bg-panel border border-border-subtle rounded-sm shadow-xl overflow-hidden">
            <div className="panel-header">
              <span className="flex-1">Pre-Trade Risk Check</span>
              <button
                type="button"
                onClick={handleRiskCancel}
                className="font-mono text-[0.6rem] text-text-muted hover:text-text-secondary transition-colors"
              >
                ✕
              </button>
            </div>
            <div className="p-2.5">
              <PreTradeRiskCheck />
            </div>
            <div className="flex gap-1.5 px-2.5 pb-2.5">
              <button
                type="button"
                onClick={handleRiskCancel}
                className="flex-1 py-1.5 font-mono text-[0.6rem] uppercase tracking-wide border border-border-subtle text-text-muted rounded-sm hover:border-accent-cyan hover:text-text-secondary transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRiskConfirm}
                className={clsx(
                  'flex-1 py-1.5 font-mono text-[0.68rem] font-bold uppercase tracking-wider rounded-sm border transition-colors',
                  side === 'BUY'
                    ? 'bg-positive border-positive text-bg-root hover:bg-[#00c865]'
                    : 'bg-negative border-negative text-white hover:bg-[#e01040]'
                )}
              >
                Confirm {side}
              </button>
            </div>
          </div>
        </div>
      )}
    </form>
  )
}

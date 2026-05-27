import React, { useState, useMemo } from 'react'
import clsx from 'clsx'

// ── Types ─────────────────────────────────────────────────────────────────────

type OptionRight = 'CALL' | 'PUT'
type LegSide = 'BUY' | 'SELL'

interface SpreadLeg {
  id: string
  strike: number
  expiry: string
  right: OptionRight
  qty: number
  bid: number
  ask: number
  side: LegSide
  delta: number
  gamma: number
  theta: number
  vega: number
}

type Strategy =
  | 'Vertical'
  | 'Calendar'
  | 'Diagonal'
  | 'Straddle'
  | 'Strangle'
  | 'Butterfly'
  | 'Condor'

const STRATEGIES: Strategy[] = ['Vertical', 'Calendar', 'Diagonal', 'Straddle', 'Strangle', 'Butterfly', 'Condor']

const EXPIRIES = ['2025-06-20', '2025-07-18', '2025-08-15', '2025-09-19']

interface SpreadBuilderProps {
  /** Underlying symbol */
  symbol?: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

let _legIdCounter = 0
function newLegId() { return `leg-${++_legIdCounter}` }

function mockLeg(strike: number, right: OptionRight, side: LegSide, expiry = EXPIRIES[0]): SpreadLeg {
  const basePrice = Math.max(0.5, Math.random() * 5 + 1)
  return {
    id: newLegId(),
    strike,
    expiry,
    right,
    qty: 1,
    side,
    bid: parseFloat((basePrice - 0.05).toFixed(2)),
    ask: parseFloat((basePrice + 0.05).toFixed(2)),
    delta: side === 'BUY' ? (right === 'CALL' ? 0.45 : -0.45) : (right === 'CALL' ? -0.45 : 0.45),
    gamma: 0.05,
    theta: -0.12,
    vega: 0.18,
  }
}

function buildStrategyLegs(strategy: Strategy, atm = 185): SpreadLeg[] {
  switch (strategy) {
    case 'Vertical':
      return [mockLeg(atm, 'CALL', 'BUY'), mockLeg(atm + 5, 'CALL', 'SELL')]
    case 'Calendar':
      return [
        mockLeg(atm, 'CALL', 'BUY', EXPIRIES[1]),
        mockLeg(atm, 'CALL', 'SELL', EXPIRIES[0]),
      ]
    case 'Diagonal':
      return [
        mockLeg(atm, 'CALL', 'BUY', EXPIRIES[1]),
        mockLeg(atm + 5, 'CALL', 'SELL', EXPIRIES[0]),
      ]
    case 'Straddle':
      return [mockLeg(atm, 'CALL', 'BUY'), mockLeg(atm, 'PUT', 'BUY')]
    case 'Strangle':
      return [mockLeg(atm + 10, 'CALL', 'BUY'), mockLeg(atm - 10, 'PUT', 'BUY')]
    case 'Butterfly':
      return [
        mockLeg(atm - 5, 'CALL', 'BUY'),
        mockLeg(atm, 'CALL', 'SELL'),
        mockLeg(atm, 'CALL', 'SELL'),
        mockLeg(atm + 5, 'CALL', 'BUY'),
      ]
    case 'Condor':
      return [
        mockLeg(atm - 10, 'PUT', 'BUY'),
        mockLeg(atm - 5, 'PUT', 'SELL'),
        mockLeg(atm + 5, 'CALL', 'SELL'),
        mockLeg(atm + 10, 'CALL', 'BUY'),
      ]
  }
}

function netPremium(legs: SpreadLeg[]): number {
  return legs.reduce((sum, leg) => {
    const mid = (leg.bid + leg.ask) / 2
    return sum + (leg.side === 'BUY' ? -mid : mid) * leg.qty
  }, 0)
}

function netGreeks(legs: SpreadLeg[]) {
  return legs.reduce(
    (acc, leg) => ({
      delta: acc.delta + leg.delta * leg.qty * (leg.side === 'BUY' ? 1 : -1),
      gamma: acc.gamma + leg.gamma * leg.qty * (leg.side === 'BUY' ? 1 : -1),
      theta: acc.theta + leg.theta * leg.qty * (leg.side === 'BUY' ? 1 : -1),
      vega: acc.vega + leg.vega * leg.qty * (leg.side === 'BUY' ? 1 : -1),
    }),
    { delta: 0, gamma: 0, theta: 0, vega: 0 },
  )
}

// Simplified P&L at expiry for each price point
function payoffAtPrice(legs: SpreadLeg[], underlyingPrice: number): number {
  const premium = netPremium(legs)
  const intrinsic = legs.reduce((sum, leg) => {
    const val =
      leg.right === 'CALL'
        ? Math.max(0, underlyingPrice - leg.strike)
        : Math.max(0, leg.strike - underlyingPrice)
    return sum + (leg.side === 'BUY' ? val : -val) * leg.qty
  }, 0)
  return (intrinsic + premium) * 100
}

// ── Payoff SVG Diagram ────────────────────────────────────────────────────────

interface PayoffDiagramProps {
  legs: SpreadLeg[]
  currentPrice: number
}

function PayoffDiagram({ legs, currentPrice }: PayoffDiagramProps) {
  const WIDTH = 320
  const HEIGHT = 120
  const PADDING = { top: 10, right: 12, bottom: 24, left: 44 }
  const innerW = WIDTH - PADDING.left - PADDING.right
  const innerH = HEIGHT - PADDING.top - PADDING.bottom

  const priceRange = useMemo(() => {
    const lo = currentPrice * 0.80
    const hi = currentPrice * 1.20
    const points: { price: number; pnl: number }[] = []
    const steps = 60
    for (let i = 0; i <= steps; i++) {
      const price = lo + (hi - lo) * (i / steps)
      points.push({ price, pnl: legs.length > 0 ? payoffAtPrice(legs, price) : 0 })
    }
    return { lo, hi, points }
  }, [legs, currentPrice])

  const pnls = priceRange.points.map(p => p.pnl)
  const minPnl = Math.min(...pnls, 0)
  const maxPnl = Math.max(...pnls, 0)
  const pnlRange = Math.max(maxPnl - minPnl, 1)

  function toX(price: number): number {
    return PADDING.left + ((price - priceRange.lo) / (priceRange.hi - priceRange.lo)) * innerW
  }
  function toY(pnl: number): number {
    return PADDING.top + (1 - (pnl - minPnl) / pnlRange) * innerH
  }

  const zeroY = toY(0)
  const currentX = toX(currentPrice)

  // Build SVG path
  const pathPoints = priceRange.points.map(p => `${toX(p.price).toFixed(1)},${toY(p.pnl).toFixed(1)}`).join(' ')

  // Breakeven crossings (sign change points)
  const breakevens: number[] = []
  for (let i = 1; i < priceRange.points.length; i++) {
    const prev = priceRange.points[i - 1]
    const curr = priceRange.points[i]
    if (prev.pnl * curr.pnl < 0) {
      const t = prev.pnl / (prev.pnl - curr.pnl)
      breakevens.push(prev.price + t * (curr.price - prev.price))
    }
  }

  return (
    <div className="bg-bg-root border border-border-subtle rounded-sm overflow-hidden">
      <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest px-2 pt-1.5 pb-0.5">
        Payoff at Expiry
      </p>
      <svg width={WIDTH} height={HEIGHT} className="block">
        {/* Zero line */}
        <line
          x1={PADDING.left} y1={zeroY} x2={PADDING.left + innerW} y2={zeroY}
          stroke="#1e1e1e" strokeWidth="1"
        />

        {/* Profit fill area (above zero) */}
        <clipPath id="clip-above">
          <rect x={PADDING.left} y={PADDING.top} width={innerW} height={zeroY - PADDING.top} />
        </clipPath>
        <polyline
          points={pathPoints}
          fill="none"
          stroke="#00e676"
          strokeWidth="1.5"
          clipPath="url(#clip-above)"
        />

        {/* Loss fill area (below zero) */}
        <clipPath id="clip-below">
          <rect x={PADDING.left} y={zeroY} width={innerW} height={PADDING.top + innerH - zeroY} />
        </clipPath>
        <polyline
          points={pathPoints}
          fill="none"
          stroke="#ff1744"
          strokeWidth="1.5"
          clipPath="url(#clip-below)"
        />

        {/* Whole line (thin guide) */}
        <polyline
          points={pathPoints}
          fill="none"
          stroke="#444444"
          strokeWidth="0.5"
        />

        {/* Current price marker */}
        <line
          x1={currentX} y1={PADDING.top} x2={currentX} y2={PADDING.top + innerH}
          stroke="#ff6600" strokeWidth="1" strokeDasharray="3,2"
        />
        <text x={currentX + 2} y={PADDING.top + 8} fill="#ff6600" fontSize="7" fontFamily="monospace">
          {currentPrice.toFixed(0)}
        </text>

        {/* Breakeven markers */}
        {breakevens.map((be, i) => (
          <g key={i}>
            <line
              x1={toX(be)} y1={PADDING.top} x2={toX(be)} y2={PADDING.top + innerH}
              stroke="#ffcc00" strokeWidth="0.75" strokeDasharray="2,2"
            />
            <text x={toX(be) + 2} y={PADDING.top + innerH + 10} fill="#ffcc00" fontSize="6.5" fontFamily="monospace">
              {be.toFixed(1)}
            </text>
          </g>
        ))}

        {/* Y-axis labels */}
        <text x={PADDING.left - 4} y={PADDING.top + 4} fill="#444444" fontSize="7" fontFamily="monospace" textAnchor="end">
          {(maxPnl / 1000).toFixed(1)}k
        </text>
        <text x={PADDING.left - 4} y={zeroY + 4} fill="#444444" fontSize="7" fontFamily="monospace" textAnchor="end">
          0
        </text>
        <text x={PADDING.left - 4} y={PADDING.top + innerH} fill="#444444" fontSize="7" fontFamily="monospace" textAnchor="end">
          {(minPnl / 1000).toFixed(1)}k
        </text>
      </svg>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function SpreadBuilder({ symbol = 'AAPL' }: SpreadBuilderProps) {
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy>('Vertical')
  const [legs, setLegs] = useState<SpreadLeg[]>(() => buildStrategyLegs('Vertical'))
  const [currentPrice] = useState(185)
  const [saved, setSaved] = useState(false)

  const premium = netPremium(legs)
  const greeks = netGreeks(legs)

  function handleStrategyChange(strategy: Strategy) {
    setSelectedStrategy(strategy)
    setLegs(buildStrategyLegs(strategy, currentPrice))
  }

  function addLeg() {
    setLegs(prev => [...prev, mockLeg(currentPrice + 5, 'CALL', 'BUY')])
  }

  function removeLeg(id: string) {
    setLegs(prev => prev.filter(l => l.id !== id))
  }

  function updateLeg(id: string, partial: Partial<SpreadLeg>) {
    setLegs(prev => prev.map(l => l.id === id ? { ...l, ...partial } : l))
  }

  function handleSave() {
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="panel-header">
        <span className="flex-1">◈ Spread Builder</span>
        <span className="font-mono text-[0.65rem] text-accent-cyan font-semibold">{symbol}</span>
      </div>

      <div className="px-2.5 pt-2 space-y-2 overflow-y-auto flex-1">
        {/* Strategy selector */}
        <div>
          <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
            Strategy
          </label>
          <div className="flex flex-wrap gap-0.5">
            {STRATEGIES.map(s => (
              <button
                key={s}
                type="button"
                onClick={() => handleStrategyChange(s)}
                className={clsx(
                  'px-2 py-1 font-mono text-[0.55rem] uppercase tracking-wide border rounded-sm transition-colors',
                  selectedStrategy === s
                    ? 'bg-bg-panel-raised border-accent-cyan text-accent-cyan'
                    : 'border-border-subtle text-text-muted hover:border-accent-cyan hover:text-text-secondary',
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* Payoff diagram */}
        <PayoffDiagram legs={legs} currentPrice={currentPrice} />

        {/* Leg table */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">Legs</span>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={addLeg}
                className="px-1.5 py-0.5 font-mono text-[0.55rem] border border-border-subtle text-text-muted hover:border-accent-cyan hover:text-text-secondary rounded-sm transition-colors"
              >
                + Add Leg
              </button>
            </div>
          </div>

          <div className="border border-border-subtle rounded-sm overflow-hidden">
            <table className="w-full border-collapse">
              <thead>
                <tr className="bg-bg-panel border-b border-border-subtle">
                  {['Side', 'Strike', 'Exp', 'C/P', 'Qty', 'Bid', 'Ask', ''].map(h => (
                    <th key={h} className="py-1 px-1.5 font-mono text-[0.5rem] uppercase tracking-wider text-text-muted text-left">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {legs.map(leg => (
                  <tr key={leg.id} className="border-b border-border-muted hover:bg-bg-panel-hover">
                    <td className="py-0.5 px-1.5">
                      <button
                        type="button"
                        onClick={() => updateLeg(leg.id, { side: leg.side === 'BUY' ? 'SELL' : 'BUY' })}
                        className={clsx('font-mono text-[0.6rem] font-semibold', leg.side === 'BUY' ? 'text-positive' : 'text-negative')}
                      >
                        {leg.side}
                      </button>
                    </td>
                    <td className="py-0.5 px-1.5">
                      <input
                        type="number"
                        value={leg.strike}
                        onChange={e => updateLeg(leg.id, { strike: Number(e.target.value) })}
                        className="w-14 bg-transparent font-mono text-[0.6rem] text-text-primary tabular-nums border-b border-border-subtle focus:outline-none focus:border-accent-cyan"
                      />
                    </td>
                    <td className="py-0.5 px-1.5">
                      <select
                        value={leg.expiry}
                        onChange={e => updateLeg(leg.id, { expiry: e.target.value })}
                        className="bg-transparent font-mono text-[0.55rem] text-text-secondary focus:outline-none"
                      >
                        {EXPIRIES.map(exp => <option key={exp} value={exp}>{exp.slice(5)}</option>)}
                      </select>
                    </td>
                    <td className="py-0.5 px-1.5">
                      <button
                        type="button"
                        onClick={() => updateLeg(leg.id, { right: leg.right === 'CALL' ? 'PUT' : 'CALL' })}
                        className={clsx('font-mono text-[0.6rem] font-semibold', leg.right === 'CALL' ? 'text-positive' : 'text-negative')}
                      >
                        {leg.right[0]}
                      </button>
                    </td>
                    <td className="py-0.5 px-1.5">
                      <input
                        type="number"
                        min="1"
                        value={leg.qty}
                        onChange={e => updateLeg(leg.id, { qty: Number(e.target.value) })}
                        className="w-8 bg-transparent font-mono text-[0.6rem] text-text-primary tabular-nums border-b border-border-subtle focus:outline-none focus:border-accent-cyan"
                      />
                    </td>
                    <td className="py-0.5 px-1.5 font-mono text-[0.6rem] text-text-secondary tabular-nums">{leg.bid.toFixed(2)}</td>
                    <td className="py-0.5 px-1.5 font-mono text-[0.6rem] text-text-secondary tabular-nums">{leg.ask.toFixed(2)}</td>
                    <td className="py-0.5 px-1">
                      <button
                        type="button"
                        onClick={() => removeLeg(leg.id)}
                        className="font-mono text-[0.6rem] text-negative hover:text-accent-red transition-colors"
                        title="Remove leg"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Net premium */}
        <div className="flex items-center justify-between p-2 bg-bg-root border border-border-subtle rounded-sm">
          <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">
            Net {premium >= 0 ? 'Credit' : 'Debit'}
          </span>
          <span className={clsx(
            'font-mono text-sm font-semibold tabular-nums',
            premium >= 0 ? 'text-positive' : 'text-negative',
          )}>
            {premium >= 0 ? '+' : ''}{premium.toFixed(2)} / contract
          </span>
        </div>

        {/* Greeks summary */}
        <div className="p-2 bg-bg-root border border-border-subtle rounded-sm">
          <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1.5">Net Greeks</p>
          <div className="grid grid-cols-4 gap-1">
            {[
              { label: 'Delta', value: greeks.delta, color: greeks.delta > 0 ? 'text-positive' : greeks.delta < 0 ? 'text-negative' : 'text-text-primary' },
              { label: 'Gamma', value: greeks.gamma, color: 'text-accent-cyan' },
              { label: 'Theta', value: greeks.theta, color: greeks.theta < 0 ? 'text-negative' : 'text-positive' },
              { label: 'Vega', value: greeks.vega, color: 'text-accent-amber' },
            ].map(({ label, value, color }) => (
              <div key={label} className="text-center">
                <div className="font-mono text-[0.5rem] text-text-muted uppercase mb-0.5">{label}</div>
                <div className={clsx('font-mono text-[0.7rem] tabular-nums font-medium', color)}>
                  {value.toFixed(3)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-1.5 px-2.5 pb-2.5 pt-2">
        <button
          type="button"
          onClick={handleSave}
          className={clsx(
            'flex-1 py-1.5 font-mono text-[0.68rem] font-bold uppercase tracking-wider rounded-sm border transition-colors',
            saved
              ? 'bg-positive border-positive text-bg-root'
              : 'bg-bg-panel-raised border-accent-cyan text-accent-cyan hover:bg-bg-panel',
          )}
        >
          {saved ? '✓ Strategy Saved' : 'Save Strategy'}
        </button>
      </div>
    </div>
  )
}

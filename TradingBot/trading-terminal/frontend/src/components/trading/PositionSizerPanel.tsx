import React, { useState, useMemo } from 'react'
import clsx from 'clsx'

// ── Props ─────────────────────────────────────────────────────────────────────

interface PositionSizerPanelProps {
  /** Total portfolio value in dollars */
  portfolioValue?: number
  /** Current price of the instrument */
  currentPrice?: number
  /** Agent win rate 0–1 */
  agentWinRate?: number
  /** Agent average win in dollars */
  agentAvgWin?: number
  /** Agent average loss in dollars */
  agentAvgLoss?: number
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(1)}K`
  return `$${v.toFixed(2)}`
}

function pct(v: number): string { return `${(v * 100).toFixed(2)}%` }

function kellyFraction(winRate: number, avgWin: number, avgLoss: number): number {
  if (avgLoss <= 0 || winRate <= 0 || winRate >= 1) return 0
  const b = avgWin / avgLoss
  const p = winRate
  const q = 1 - p
  return Math.max(0, (b * p - q) / b)
}

// ── Risk gauge ────────────────────────────────────────────────────────────────

function RiskGauge({ riskPct }: { riskPct: number }) {
  const clamped = Math.min(5, Math.max(0, riskPct))
  const fillPct = (clamped / 5) * 100
  const color = clamped > 2 ? 'bg-negative' : clamped > 1 ? 'bg-warning' : 'bg-positive'
  const textColor = clamped > 2 ? 'text-negative' : clamped > 1 ? 'text-warning' : 'text-positive'
  const label = clamped > 2 ? 'HIGH RISK' : clamped > 1 ? 'MODERATE' : 'WITHIN LIMIT'

  return (
    <div className="p-2 bg-bg-root border border-border-subtle rounded-sm">
      <div className="flex items-center justify-between mb-1.5">
        <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">Portfolio Risk</span>
        <span className={clsx('font-mono text-[0.65rem] font-semibold', textColor)}>{label}</span>
      </div>
      <div className="relative h-3 bg-bg-panel-raised rounded-full overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all duration-300', color)}
          style={{ width: `${fillPct}%` }}
        />
        {/* Tick marks at 1% and 2% */}
        <div className="absolute top-0 bottom-0 left-[20%] w-px bg-border-subtle" />
        <div className="absolute top-0 bottom-0 left-[40%] w-px bg-border-subtle" />
      </div>
      <div className="flex justify-between mt-0.5">
        <span className="font-mono text-[0.5rem] text-text-muted">0%</span>
        <span className="font-mono text-[0.5rem] text-positive">1%</span>
        <span className="font-mono text-[0.5rem] text-warning">2%</span>
        <span className="font-mono text-[0.5rem] text-text-muted">5%</span>
      </div>
      <div className="text-center mt-1">
        <span className={clsx('font-mono text-sm font-bold tabular-nums', textColor)}>
          {clamped.toFixed(2)}% at risk
        </span>
      </div>
    </div>
  )
}

// ── Slider ────────────────────────────────────────────────────────────────────

function TerminalSlider({
  label,
  min,
  max,
  step,
  value,
  onChange,
  formatDisplay,
}: {
  label: string
  min: number
  max: number
  step: number
  value: number
  onChange: (v: number) => void
  formatDisplay: (v: number) => string
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <label className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">{label}</label>
        <span className="font-mono text-[0.65rem] text-accent-cyan tabular-nums font-semibold">
          {formatDisplay(value)}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full h-1 bg-bg-panel-raised rounded-full appearance-none cursor-pointer
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-cyan
          [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-bg-root"
      />
      <div className="flex justify-between mt-0.5">
        <span className="font-mono text-[0.5rem] text-text-muted">{formatDisplay(min)}</span>
        <span className="font-mono text-[0.5rem] text-text-muted">{formatDisplay(max)}</span>
      </div>
    </div>
  )
}

// ── Output row ────────────────────────────────────────────────────────────────

function OutputRow({ label, value, color, highlight }: { label: string; value: string; color?: string; highlight?: boolean }) {
  return (
    <div className={clsx(
      'flex items-center justify-between py-1',
      highlight ? 'border-b border-accent-cyan/20' : 'border-b border-border-muted',
      'last:border-0',
    )}>
      <span className="font-mono text-[0.58rem] text-text-muted">{label}</span>
      <span className={clsx('font-mono text-[0.72rem] tabular-nums font-medium', color ?? 'text-text-primary')}>
        {value}
      </span>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function PositionSizerPanel({
  portfolioValue = 100000,
  currentPrice = 185,
  agentWinRate = 0.55,
  agentAvgWin = 500,
  agentAvgLoss = 300,
}: PositionSizerPanelProps) {
  const [accountSize, setAccountSize] = useState(portfolioValue)
  const [riskPercent, setRiskPercent] = useState(1)
  const [winRate, setWinRate] = useState(agentWinRate * 100)
  const [avgWin, setAvgWin] = useState(agentAvgWin)
  const [avgLoss, setAvgLoss] = useState(agentAvgLoss)
  const [price, setPrice] = useState(currentPrice)
  const [stopMode, setStopMode] = useState<'$' | '%'>('$')
  const [stopValue, setStopValue] = useState(5)

  const results = useMemo(() => {
    const stopDollar = stopMode === '$'
      ? stopValue
      : price * (stopValue / 100)
    const dollarRisk = accountSize * (riskPercent / 100)
    const shares = stopDollar > 0 ? Math.floor(dollarRisk / stopDollar) : 0
    const positionValue = shares * price
    const portfolioWeight = accountSize > 0 ? (positionValue / accountSize) * 100 : 0

    const kelly = kellyFraction(winRate / 100, avgWin, avgLoss)
    const halfKelly = kelly / 2

    return {
      kelly,
      halfKelly,
      shares,
      dollarRisk,
      positionValue,
      portfolioWeight,
      riskPct: accountSize > 0 ? (dollarRisk / accountSize) * 100 : 0,
      stopDollar,
    }
  }, [accountSize, riskPercent, winRate, avgWin, avgLoss, price, stopMode, stopValue])

  const policyViolation = results.riskPct > 2 || results.portfolioWeight > 10

  return (
    <div className="flex flex-col h-full">
      <div className="panel-header">
        <span className="flex-1">◈ Position Sizer</span>
      </div>

      <div className="px-2.5 pt-2 space-y-2.5 overflow-y-auto flex-1">
        {/* Inputs */}
        <div>
          <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
            Account Size ($)
          </label>
          <input
            type="number"
            min="1"
            step="1000"
            value={accountSize}
            onChange={e => setAccountSize(Number(e.target.value))}
            className="terminal-input h-7 tabular-nums"
          />
        </div>

        <TerminalSlider
          label="Risk Per Trade"
          min={0.5}
          max={5}
          step={0.25}
          value={riskPercent}
          onChange={setRiskPercent}
          formatDisplay={v => `${v.toFixed(2)}%`}
        />

        <TerminalSlider
          label="Win Rate"
          min={10}
          max={90}
          step={1}
          value={winRate}
          onChange={setWinRate}
          formatDisplay={v => `${v.toFixed(0)}%`}
        />

        <div className="grid grid-cols-2 gap-1.5">
          <div>
            <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
              Avg Win ($)
            </label>
            <input
              type="number"
              min="0"
              value={avgWin}
              onChange={e => setAvgWin(Number(e.target.value))}
              className="terminal-input h-7 tabular-nums"
            />
          </div>
          <div>
            <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
              Avg Loss ($)
            </label>
            <input
              type="number"
              min="0"
              value={avgLoss}
              onChange={e => setAvgLoss(Number(e.target.value))}
              className="terminal-input h-7 tabular-nums"
            />
          </div>
        </div>

        <div>
          <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">
            Current Price ($)
          </label>
          <input
            type="number"
            min="0.01"
            step="0.01"
            value={price}
            onChange={e => setPrice(Number(e.target.value))}
            className="terminal-input h-7 tabular-nums"
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-0.5">
            <label className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">Stop Loss</label>
            <div className="flex border border-border-subtle rounded-sm overflow-hidden">
              {(['$', '%'] as const).map(m => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setStopMode(m)}
                  className={clsx(
                    'px-2 py-0.5 font-mono text-[0.55rem] transition-colors',
                    stopMode === m ? 'bg-bg-panel-raised text-accent-cyan' : 'text-text-muted hover:text-text-secondary',
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
          <input
            type="number"
            min="0.01"
            step={stopMode === '$' ? '0.01' : '0.1'}
            value={stopValue}
            onChange={e => setStopValue(Number(e.target.value))}
            className="terminal-input h-7 tabular-nums"
          />
          {stopMode === '$' && (
            <p className="font-mono text-[0.5rem] text-text-muted mt-0.5">
              Stop ${results.stopDollar.toFixed(2)} below entry ({pct(results.stopDollar / price)} move)
            </p>
          )}
        </div>

        {/* Kelly outputs */}
        <div className="p-2 bg-bg-root border border-border-subtle rounded-sm">
          <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1">Kelly Criterion</p>
          <div className="grid grid-cols-2 gap-1">
            <div className="text-center p-1.5 bg-bg-panel-raised rounded-sm">
              <div className="font-mono text-[0.5rem] text-text-muted mb-0.5">Full Kelly</div>
              <div className="font-mono text-sm font-bold text-accent-amber tabular-nums">
                {pct(results.kelly)}
              </div>
            </div>
            <div className="text-center p-1.5 bg-bg-panel-raised rounded-sm">
              <div className="font-mono text-[0.5rem] text-text-muted mb-0.5">Half Kelly</div>
              <div className="font-mono text-sm font-bold text-accent-cyan tabular-nums">
                {pct(results.halfKelly)}
              </div>
            </div>
          </div>
        </div>

        {/* Sizing outputs */}
        <div className="p-2 bg-bg-root border border-border-subtle rounded-sm">
          <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1">Recommended Sizing</p>
          <OutputRow label="Position Size" value={`${results.shares.toLocaleString()} shares`} color="text-accent-cyan" highlight />
          <OutputRow label="Dollar Risk" value={fmt$(results.dollarRisk)} color="text-negative" />
          <OutputRow label="Max Position Value" value={fmt$(results.positionValue)} />
          <OutputRow label="Portfolio Weight" value={`${results.portfolioWeight.toFixed(1)}%`}
            color={results.portfolioWeight > 10 ? 'text-negative' : results.portfolioWeight > 5 ? 'text-warning' : 'text-positive'} />
        </div>

        {/* Risk gauge */}
        <RiskGauge riskPct={results.riskPct} />

        {/* Warning */}
        {policyViolation && (
          <div className="p-2 bg-negative-bg border border-negative rounded-sm">
            <p className="font-mono text-[0.62rem] text-negative font-semibold uppercase tracking-wide">
              Policy Warning
            </p>
            <p className="font-mono text-[0.6rem] text-negative mt-0.5">
              {results.riskPct > 2 && `Risk ${results.riskPct.toFixed(2)}% exceeds 2% limit. `}
              {results.portfolioWeight > 10 && `Position weight ${results.portfolioWeight.toFixed(1)}% exceeds 10% limit.`}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

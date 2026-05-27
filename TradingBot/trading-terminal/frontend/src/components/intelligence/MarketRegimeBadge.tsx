import React from 'react'
import clsx from 'clsx'

// ── Types ────────────────────────────────────────────────────────────────────

type RegimeKey =
  | 'BULL_QUIET'
  | 'BULL_VOLATILE'
  | 'BEAR_QUIET'
  | 'BEAR_VOLATILE'
  | 'NEUTRAL'

interface RegimeConfig {
  icon: string
  label: string
  pillBg: string
  pillText: string
  description: string
  implications: string
}

/**
 * Props for MarketRegimeBadge.
 * @prop regime    - Market regime key. Defaults to BULL_QUIET.
 * @prop confidence - 0–100 confidence value. Defaults to 72.
 * @prop variant   - 'badge' renders compact inline pill; 'panel' renders full info panel.
 */
export interface MarketRegimeBadgeProps {
  regime?: string
  confidence?: number
  variant?: 'badge' | 'panel'
}

// ── Regime configuration map ─────────────────────────────────────────────────

const REGIME_CONFIG: Record<RegimeKey, RegimeConfig> = {
  BULL_QUIET: {
    icon: '◆',
    label: 'BULL QUIET',
    pillBg: 'bg-positive-bg border border-positive-dim',
    pillText: 'text-positive',
    description: 'Low-volatility uptrend. Steady institutional accumulation.',
    implications: 'Sell premium, run theta strategies. Iron condors, covered calls.',
  },
  BULL_VOLATILE: {
    icon: '◆',
    label: 'BULL VOLATILE',
    pillBg: 'bg-warning-bg border border-warning-dim',
    pillText: 'text-warning',
    description: 'Uptrend with elevated realized volatility. Momentum-driven moves.',
    implications: 'Long gamma plays, straddles, momentum breakouts. Tight stops.',
  },
  BEAR_QUIET: {
    icon: '◆',
    label: 'BEAR QUIET',
    pillBg: 'bg-[rgba(255,102,0,0.1)] border border-[rgba(255,102,0,0.3)]',
    pillText: 'text-accent-cyan',
    description: 'Slow-grind downtrend. Defensive rotation, low breadth.',
    implications: 'Reduce longs, hold cash, short weak sectors. Put spreads.',
  },
  BEAR_VOLATILE: {
    icon: '▼',
    label: 'BEAR VOLATILE',
    pillBg: 'bg-negative-bg border border-negative-dim',
    pillText: 'text-negative',
    description: 'High-fear environment. Panic selling, forced de-risking.',
    implications: 'Long puts, inverse ETFs, VIX calls. Avoid catching knives.',
  },
  NEUTRAL: {
    icon: '●',
    label: 'NEUTRAL',
    pillBg: 'bg-bg-panel-raised border border-border-subtle',
    pillText: 'text-text-secondary',
    description: 'No directional edge. Mixed signals, choppy tape.',
    implications: 'Range strategies, pairs trading. Reduce position size.',
  },
}

function toRegimeKey(regime: string | undefined): RegimeKey {
  if (regime && regime in REGIME_CONFIG) return regime as RegimeKey
  return 'BULL_QUIET'
}

// ── Badge variant ─────────────────────────────────────────────────────────────

function RegimeBadge({ regime, confidence }: { regime: RegimeKey; confidence: number }) {
  const cfg = REGIME_CONFIG[regime]
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-sm font-mono text-[0.62rem] font-semibold tracking-wide',
        cfg.pillBg,
        cfg.pillText,
      )}
    >
      <span>{cfg.icon}</span>
      <span>{cfg.label}</span>
      <span className="text-[0.55rem] opacity-70 tabular-nums">{confidence}%</span>
    </span>
  )
}

// ── Panel variant ─────────────────────────────────────────────────────────────

function RegimePanel({ regime, confidence }: { regime: RegimeKey; confidence: number }) {
  const cfg = REGIME_CONFIG[regime]
  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Market Regime</span>
      </div>

      {/* Regime display */}
      <div className="px-3 py-4 flex flex-col gap-3 border-b border-border-subtle">
        <div className="flex items-center gap-3">
          <span
            className={clsx(
              'text-2xl font-mono font-bold',
              cfg.pillText,
            )}
          >
            {cfg.icon}
          </span>
          <div>
            <div className={clsx('font-mono text-lg font-bold tracking-widest', cfg.pillText)}>
              {cfg.label}
            </div>
            <div className="font-mono text-[0.6rem] text-text-muted uppercase tracking-widest mt-0.5">
              Current Regime
            </div>
          </div>
        </div>
        <p className="font-mono text-[0.67rem] text-text-secondary leading-relaxed">
          {cfg.description}
        </p>
      </div>

      {/* Confidence bar */}
      <div className="px-3 py-3 border-b border-border-subtle">
        <div className="flex justify-between items-center mb-1.5">
          <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">
            Model Confidence
          </span>
          <span className={clsx('font-mono text-[0.7rem] font-semibold tabular-nums', cfg.pillText)}>
            {confidence}%
          </span>
        </div>
        <div className="h-1.5 bg-bg-panel-raised border border-border-subtle rounded-none overflow-hidden">
          <div
            className={clsx(
              'h-full transition-all',
              regime === 'BULL_QUIET' ? 'bg-positive' :
              regime === 'BULL_VOLATILE' ? 'bg-warning' :
              regime === 'BEAR_QUIET' ? 'bg-accent-cyan' :
              regime === 'BEAR_VOLATILE' ? 'bg-negative' :
              'bg-text-secondary',
            )}
            style={{ width: `${confidence}%` }}
          />
        </div>
      </div>

      {/* Trading implications */}
      <div className="px-3 py-3">
        <div className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1.5">
          Trading Implications
        </div>
        <div className="flex items-start gap-2">
          <span className="text-accent-cyan text-[0.6rem] mt-px">›</span>
          <p className="font-mono text-[0.67rem] text-text-secondary leading-relaxed">
            {cfg.implications}
          </p>
        </div>
      </div>

      {/* Regime legend */}
      <div className="px-3 pb-3 mt-1">
        <div className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1.5">
          All Regimes
        </div>
        <div className="space-y-1">
          {(Object.entries(REGIME_CONFIG) as [RegimeKey, RegimeConfig][]).map(([key, c]) => (
            <div
              key={key}
              className={clsx(
                'flex items-center gap-2 px-2 py-1 rounded-sm',
                key === regime ? 'bg-bg-panel-raised' : '',
              )}
            >
              <span className={clsx('font-mono text-[0.62rem]', c.pillText)}>{c.icon}</span>
              <span className={clsx('font-mono text-[0.6rem]', key === regime ? c.pillText : 'text-text-muted')}>
                {c.label}
              </span>
              {key === regime && (
                <span className="ml-auto font-mono text-[0.55rem] text-accent-cyan">← ACTIVE</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function MarketRegimeBadge({
  regime,
  confidence = 72,
  variant = 'badge',
}: MarketRegimeBadgeProps) {
  const key = toRegimeKey(regime)
  if (variant === 'panel') {
    return <RegimePanel regime={key} confidence={confidence} />
  }
  return <RegimeBadge regime={key} confidence={confidence} />
}

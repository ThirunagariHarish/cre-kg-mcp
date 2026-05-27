import React from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import {
  ArrowUpCircle,
  ArrowDownCircle,
  MinusCircle,
  ChevronUp,
  Zap,
  Eye,
  X,
} from 'lucide-react'
import type { Signal } from '@/types/signals'
import SignalBadge from './SignalBadge'

interface SignalCardProps {
  signal: Signal
  expanded?: boolean
  onCollapse?: () => void
  onExecute: () => void
  onDismiss: () => void
  onAnalyze: () => void
  className?: string
}

export default function SignalCard({
  signal,
  expanded = false,
  onCollapse,
  onExecute,
  onDismiss,
  onAnalyze,
  className,
}: SignalCardProps) {
  const timeAgo = formatDistanceToNow(signal.receivedAt, { addSuffix: true })
  const confidence = signal.confidence
  const isHigh = (confidence ?? 0) >= 70
  const isMedium = (confidence ?? 0) >= 40 && (confidence ?? 0) < 70

  const borderColor = signal.direction === 'BUY'
    ? 'border-l-positive'
    : signal.direction === 'SELL'
      ? 'border-l-negative'
      : 'border-l-warning'

  return (
    <div
      className={clsx(
        'border-b border-border-subtle border-l-2',
        'bg-bg-panel hover:bg-bg-panel-hover transition-colors',
        borderColor,
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2.5 pt-2 pb-1">
        {/* Source */}
        <span className="font-mono text-[0.55rem] text-text-muted bg-bg-panel-raised border border-border-subtle px-1 py-px rounded-sm uppercase tracking-wider flex-shrink-0">
          {signal.source}
        </span>

        {/* Ticker */}
        <span className="font-mono text-sm font-bold text-accent-cyan tracking-wider flex-shrink-0">
          {signal.ticker}
        </span>

        {/* Direction Badge */}
        <SignalBadge direction={signal.direction} size="md" />

        {/* Confidence */}
        {confidence !== undefined && (
          <span
            className={clsx(
              'font-mono text-[0.65rem] font-medium ml-0.5',
              isHigh ? 'text-positive' : isMedium ? 'text-warning' : 'text-text-muted'
            )}
          >
            {confidence}%
          </span>
        )}

        <span className="flex-1" />

        {/* Time */}
        <span className="font-mono text-[0.55rem] text-text-muted">
          {timeAgo}
        </span>

        {/* Collapse button */}
        {expanded && onCollapse && (
          <button
            onClick={onCollapse}
            className="p-0.5 text-text-muted hover:text-text-primary rounded-sm transition-colors"
          >
            <ChevronUp size={10} />
          </button>
        )}
      </div>

      {/* Body — message preview */}
      <div className="px-2.5 pb-1">
        <p className="font-mono text-[0.65rem] text-text-secondary leading-relaxed line-clamp-3">
          {signal.rawMessage}
        </p>
      </div>

      {/* Expanded metrics */}
      {expanded && (
        <div className="px-2.5 pb-1.5">
          <div className="grid grid-cols-3 gap-1 mt-1 pt-1 border-t border-border-muted">
            {signal.price && (
              <div className="flex flex-col">
                <span className="font-mono text-[0.55rem] text-text-muted uppercase">Entry</span>
                <span className="font-mono text-[0.7rem] text-text-primary tabular-nums">
                  ${signal.price.toFixed(2)}
                </span>
              </div>
            )}
            {signal.stopLoss && (
              <div className="flex flex-col">
                <span className="font-mono text-[0.55rem] text-text-muted uppercase">Stop</span>
                <span className="font-mono text-[0.7rem] text-negative tabular-nums">
                  ${signal.stopLoss.toFixed(2)}
                </span>
              </div>
            )}
            {signal.targetPrice && (
              <div className="flex flex-col">
                <span className="font-mono text-[0.55rem] text-text-muted uppercase">Target</span>
                <span className="font-mono text-[0.7rem] text-positive tabular-nums">
                  ${signal.targetPrice.toFixed(2)}
                </span>
              </div>
            )}
          </div>

          {signal.timeframe && (
            <div className="mt-1.5 flex items-center gap-1">
              <span className="font-mono text-[0.55rem] text-text-muted uppercase">Timeframe:</span>
              <span className="font-mono text-[0.6rem] text-text-secondary">{signal.timeframe}</span>
            </div>
          )}
        </div>
      )}

      {/* Footer: Risk status + Actions */}
      <div className="flex items-center gap-1.5 px-2.5 pb-2 pt-1 border-t border-border-muted">
        {/* Status badge */}
        <span
          className={clsx(
            'font-mono text-[0.55rem] px-1 py-px rounded-sm border uppercase tracking-wide flex-shrink-0',
            signal.status === 'PENDING' && 'text-warning border-warning-dim bg-warning-bg',
            signal.status === 'ANALYZED' && 'text-accent-cyan border-accent-cyan-dim bg-info-bg',
            signal.status === 'EXECUTED' && 'text-positive border-positive-dim bg-positive-bg',
            signal.status === 'REJECTED' && 'text-negative border-negative-dim bg-negative-bg',
            signal.status === 'EXPIRED' && 'text-text-muted border-border-subtle bg-bg-panel-raised',
          )}
        >
          {signal.status}
        </span>

        <span className="flex-1" />

        {/* Actions */}
        <button
          onClick={onDismiss}
          className="flex items-center gap-0.5 px-1.5 py-0.5 font-mono text-[0.6rem] text-text-muted border border-border-subtle rounded-sm hover:border-negative hover:text-negative transition-colors"
          title="Dismiss signal"
        >
          <X size={8} />
        </button>

        <button
          onClick={onAnalyze}
          className="flex items-center gap-0.5 px-1.5 py-0.5 font-mono text-[0.6rem] text-accent-cyan border border-accent-cyan-dim rounded-sm hover:bg-info-bg transition-colors"
          title="AI Analyze"
        >
          <Eye size={8} />
          AI
        </button>

        <button
          onClick={onExecute}
          className={clsx(
            'flex items-center gap-0.5 px-1.5 py-0.5 font-mono text-[0.6rem] rounded-sm border transition-colors',
            signal.direction === 'BUY'
              ? 'text-positive border-positive-dim bg-positive-bg hover:bg-[#065f46]'
              : signal.direction === 'SELL'
                ? 'text-negative border-negative-dim bg-negative-bg hover:bg-[#7f1d1d]'
                : 'text-text-secondary border-border-subtle hover:bg-bg-panel-raised'
          )}
          title="Execute trade"
        >
          <Zap size={8} />
          EXECUTE
        </button>
      </div>
    </div>
  )
}

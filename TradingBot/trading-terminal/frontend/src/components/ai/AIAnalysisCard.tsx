import React from 'react'
import clsx from 'clsx'
import { TrendingUp, TrendingDown, Minus, Brain } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import type { AIRecommendation } from '@/types/ai'

interface AIAnalysisCardProps {
  recommendation: AIRecommendation
  compact?: boolean
  className?: string
}

export default function AIAnalysisCard({
  recommendation,
  compact = false,
  className,
}: AIAnalysisCardProps) {
  const sentimentIcon = {
    BULLISH: <TrendingUp size={10} className="text-positive" />,
    BEARISH: <TrendingDown size={10} className="text-negative" />,
    NEUTRAL: <Minus size={10} className="text-text-secondary" />,
    MIXED: <Minus size={10} className="text-warning" />,
  }[recommendation.sentiment]

  const sentimentColor = {
    BULLISH: 'text-positive',
    BEARISH: 'text-negative',
    NEUTRAL: 'text-text-secondary',
    MIXED: 'text-warning',
  }[recommendation.sentiment]

  const confidenceColor = recommendation.confidence >= 70
    ? 'text-positive'
    : recommendation.confidence >= 40
      ? 'text-warning'
      : 'text-negative'

  const actionBorder = {
    BUY: 'border-l-positive',
    SELL: 'border-l-negative',
    HOLD: 'border-l-warning',
    WATCH: 'border-l-accent-cyan',
    AVOID: 'border-l-negative',
  }[recommendation.action]

  return (
    <div
      className={clsx(
        'border border-border-subtle border-l-2 bg-bg-panel rounded-sm',
        actionBorder,
        className
      )}
    >
      {/* Header row */}
      <div className="flex items-center gap-2 px-2.5 py-2">
        <Brain size={10} className="text-accent-purple flex-shrink-0" />
        <span className="font-mono text-[0.7rem] font-bold text-accent-cyan">{recommendation.ticker}</span>
        <div className="flex items-center gap-1">
          {sentimentIcon}
          <span className={clsx('font-mono text-[0.6rem] uppercase', sentimentColor)}>
            {recommendation.sentiment}
          </span>
        </div>
        <span className={clsx('font-mono text-[0.65rem] font-semibold ml-auto tabular-nums', confidenceColor)}>
          {recommendation.confidence}%
        </span>
      </div>

      {/* Thesis */}
      <div className="px-2.5 pb-2">
        <p className={clsx(
          'font-mono text-[0.6rem] text-text-secondary leading-relaxed',
          compact && 'line-clamp-2'
        )}>
          {recommendation.thesis}
        </p>
      </div>

      {!compact && (
        <>
          {/* Factors */}
          {recommendation.keyFactors.length > 0 && (
            <div className="px-2.5 pb-1.5 border-t border-border-muted pt-1.5">
              {recommendation.keyFactors.slice(0, 3).map((f, i) => (
                <div key={i} className="flex items-start gap-1">
                  <span className="font-mono text-[0.55rem] text-accent-cyan">+</span>
                  <span className="font-mono text-[0.6rem] text-text-secondary">{f}</span>
                </div>
              ))}
            </div>
          )}

          {/* Risks */}
          {recommendation.risks.length > 0 && (
            <div className="px-2.5 pb-1.5">
              {recommendation.risks.slice(0, 2).map((r, i) => (
                <div key={i} className="flex items-start gap-1">
                  <span className="font-mono text-[0.55rem] text-negative">−</span>
                  <span className="font-mono text-[0.6rem] text-text-secondary">{r}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between px-2.5 py-1 border-t border-border-muted">
        <span className="font-mono text-[0.55rem] text-text-muted">
          {recommendation.modelName}
        </span>
        <span className="font-mono text-[0.55rem] text-text-muted">
          {formatDistanceToNow(recommendation.generatedAt, { addSuffix: true })}
        </span>
      </div>
    </div>
  )
}

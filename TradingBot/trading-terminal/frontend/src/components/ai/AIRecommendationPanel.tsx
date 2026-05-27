import React from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { Brain, TrendingUp, TrendingDown, Minus, AlertCircle, ChevronDown, ChevronUp, Zap } from 'lucide-react'
import type { AIRecommendation } from '@/types/ai'

const SENTIMENT_CONFIG = {
  BULLISH: { color: 'text-positive', icon: <TrendingUp size={10} />, bg: 'bg-positive-bg border-positive-dim' },
  BEARISH: { color: 'text-negative', icon: <TrendingDown size={10} />, bg: 'bg-negative-bg border-negative-dim' },
  NEUTRAL: { color: 'text-text-secondary', icon: <Minus size={10} />, bg: 'bg-bg-panel-raised border-border-subtle' },
  MIXED: { color: 'text-warning', icon: <Minus size={10} />, bg: 'bg-warning-bg border-warning-dim' },
}

const ACTION_CONFIG = {
  BUY: { color: 'text-positive border-positive bg-positive-bg', label: '▲ BUY' },
  SELL: { color: 'text-negative border-negative bg-negative-bg', label: '▼ SELL' },
  HOLD: { color: 'text-warning border-warning bg-warning-bg', label: '— HOLD' },
  WATCH: { color: 'text-accent-cyan border-accent-cyan bg-info-bg', label: '◉ WATCH' },
  AVOID: { color: 'text-negative border-negative-dim bg-negative-bg', label: '✕ AVOID' },
}

interface AIRecommendationPanelProps {
  recommendation?: AIRecommendation
  loading?: boolean
  onApplyToTicket?: (rec: AIRecommendation) => void
  onDismiss?: () => void
}

export default function AIRecommendationPanel({
  recommendation,
  loading = false,
  onApplyToTicket,
  onDismiss,
}: AIRecommendationPanelProps) {
  if (loading) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="panel-header">
          <Brain size={10} className="text-accent-purple animate-pulse flex-shrink-0" />
          <span className="flex-1">◈ AI Analysis</span>
          <span className="font-mono text-[0.6rem] text-accent-purple">ANALYZING...</span>
        </div>
        <div className="p-3 space-y-2">
          <div className="h-4 skeleton rounded-sm w-3/4" />
          <div className="h-3 skeleton rounded-sm" />
          <div className="h-3 skeleton rounded-sm w-4/5" />
          <div className="h-3 skeleton rounded-sm w-2/3" />
          <div className="mt-2 h-16 skeleton rounded-sm" />
        </div>
      </div>
    )
  }

  if (!recommendation) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="panel-header">
          <Brain size={10} className="text-accent-purple flex-shrink-0" />
          <span className="flex-1">◈ AI Analysis</span>
        </div>
        <div className="flex flex-col items-center justify-center flex-1 gap-2 text-text-muted p-4 text-center">
          <Brain size={20} className="text-text-muted opacity-30" />
          <span className="font-mono text-[0.65rem]">No recommendation loaded</span>
          <span className="font-mono text-[0.6rem] text-text-muted">Select a signal → AI Analyze</span>
        </div>
      </div>
    )
  }

  const sentiment = SENTIMENT_CONFIG[recommendation.sentiment]
  const actionConf = ACTION_CONFIG[recommendation.action]
  const timeAgo = formatDistanceToNow(recommendation.generatedAt, { addSuffix: true })

  const confidenceColor = recommendation.confidence >= 70
    ? 'text-positive'
    : recommendation.confidence >= 40
      ? 'text-warning'
      : 'text-negative'

  return (
    <div className="flex flex-col overflow-y-auto">
      {/* Panel Header */}
      <div className="panel-header">
        <Brain size={10} className="text-accent-purple flex-shrink-0" />
        <span className="flex-1">◈ AI Analysis</span>
        <span className="font-mono text-[0.58rem] text-accent-cyan font-semibold">{recommendation.ticker}</span>
      </div>

      {/* Rec Header */}
      <div className="flex items-start gap-2 px-2.5 pt-2 pb-1.5">
        <Brain size={12} className="text-accent-purple flex-shrink-0 mt-px" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {/* Ticker */}
            <span className="font-mono text-sm font-bold text-accent-cyan tracking-wider">
              {recommendation.ticker}
            </span>

            {/* Action */}
            <span className={clsx(
              'font-mono text-[0.65rem] font-semibold px-1.5 py-px rounded-sm border',
              actionConf.color
            )}>
              {actionConf.label}
            </span>

            {/* Sentiment */}
            <span className={clsx(
              'flex items-center gap-0.5 font-mono text-[0.6rem] px-1 py-px rounded-sm border',
              sentiment.bg, sentiment.color
            )}>
              {sentiment.icon}
              {recommendation.sentiment}
            </span>
          </div>

          {/* Confidence bar */}
          <div className="flex items-center gap-2 mt-1">
            <span className="font-mono text-[0.55rem] text-text-muted uppercase">Confidence</span>
            <div className="flex-1 h-1.5 bg-bg-panel-raised rounded-full overflow-hidden">
              <div
                className={clsx('h-full rounded-full transition-all', {
                  'bg-positive': recommendation.confidence >= 70,
                  'bg-warning': recommendation.confidence >= 40 && recommendation.confidence < 70,
                  'bg-negative': recommendation.confidence < 40,
                })}
                style={{ width: `${recommendation.confidence}%` }}
              />
            </div>
            <span className={clsx('font-mono text-[0.65rem] font-semibold tabular-nums flex-shrink-0', confidenceColor)}>
              {recommendation.confidence}%
            </span>
          </div>
        </div>
      </div>

      {/* Thesis */}
      <div className="px-2.5 pb-2 border-b border-border-subtle">
        <p className="font-mono text-[0.65rem] text-text-secondary leading-relaxed">
          {recommendation.thesis}
        </p>
      </div>

      {/* Key Metrics */}
      {(recommendation.suggestedEntry || recommendation.suggestedStopLoss || recommendation.suggestedTargetPrice) && (
        <div className="px-2.5 py-2 border-b border-border-subtle">
          <div className="grid grid-cols-3 gap-2">
            {recommendation.suggestedEntry && (
              <div>
                <span className="font-mono text-[0.55rem] text-text-muted uppercase block">Entry</span>
                <span className="font-mono text-[0.7rem] text-text-primary tabular-nums">
                  ${recommendation.suggestedEntry.toFixed(2)}
                </span>
              </div>
            )}
            {recommendation.suggestedStopLoss && (
              <div>
                <span className="font-mono text-[0.55rem] text-text-muted uppercase block">Stop</span>
                <span className="font-mono text-[0.7rem] text-negative tabular-nums">
                  ${recommendation.suggestedStopLoss.toFixed(2)}
                </span>
              </div>
            )}
            {recommendation.suggestedTargetPrice && (
              <div>
                <span className="font-mono text-[0.55rem] text-text-muted uppercase block">Target</span>
                <span className="font-mono text-[0.7rem] text-positive tabular-nums">
                  ${recommendation.suggestedTargetPrice.toFixed(2)}
                </span>
              </div>
            )}
          </div>
          {recommendation.timeframe && (
            <div className="mt-1.5 flex items-center gap-1">
              <span className="font-mono text-[0.55rem] text-text-muted uppercase">Timeframe:</span>
              <span className="font-mono text-[0.6rem] text-text-secondary">{recommendation.timeframe}</span>
            </div>
          )}
        </div>
      )}

      {/* Key Factors */}
      {recommendation.keyFactors.length > 0 && (
        <div className="px-2.5 py-2 border-b border-border-subtle">
          <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1.5">
            Key Factors
          </p>
          <div className="space-y-1">
            {recommendation.keyFactors.map((factor, i) => (
              <div key={i} className="flex items-start gap-1.5">
                <span className="font-mono text-[0.6rem] text-accent-cyan flex-shrink-0 mt-px">+</span>
                <span className="font-mono text-[0.6rem] text-text-secondary leading-relaxed">{factor}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Risks */}
      {recommendation.risks.length > 0 && (
        <div className="px-2.5 py-2 border-b border-border-subtle">
          <p className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-1.5">
            Risks
          </p>
          <div className="space-y-1">
            {recommendation.risks.map((risk, i) => (
              <div key={i} className="flex items-start gap-1.5">
                <span className="font-mono text-[0.6rem] text-negative flex-shrink-0 mt-px">−</span>
                <span className="font-mono text-[0.6rem] text-text-secondary leading-relaxed">{risk}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Disclaimer */}
      <div className="px-2.5 py-2 bg-bg-panel-raised border-b border-border-subtle">
        <div className="flex items-start gap-1.5">
          <AlertCircle size={9} className="text-warning flex-shrink-0 mt-px" />
          <p className="font-mono text-[0.55rem] text-text-muted leading-relaxed">
            {recommendation.disclaimer || 'AI ADVISORY ONLY — NOT FINANCIAL ADVICE. Past performance does not guarantee future results.'}
          </p>
        </div>
      </div>

      {/* Footer: model info + actions */}
      <div className="px-2.5 py-2">
        <div className="flex items-center justify-between mb-2">
          <span className="font-mono text-[0.55rem] text-text-muted">
            {recommendation.modelName} · {timeAgo}
          </span>
          {recommendation.promptTokens && (
            <span className="font-mono text-[0.55rem] text-text-muted">
              {((recommendation.promptTokens + (recommendation.completionTokens ?? 0)) / 1000).toFixed(1)}K tokens
            </span>
          )}
        </div>

        <div className="flex gap-1.5">
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="px-2 py-1.5 font-mono text-[0.6rem] text-text-muted border border-border-subtle rounded-sm hover:border-border-active hover:text-text-primary transition-colors"
            >
              Dismiss
            </button>
          )}
          {onApplyToTicket && (
            <button
              onClick={() => onApplyToTicket(recommendation)}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 font-mono text-[0.65rem] font-medium text-accent-cyan border border-accent-cyan-dim rounded-sm bg-info-bg hover:bg-[rgba(14,116,144,0.3)] transition-colors"
            >
              <Zap size={9} />
              Apply to Trade Ticket
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

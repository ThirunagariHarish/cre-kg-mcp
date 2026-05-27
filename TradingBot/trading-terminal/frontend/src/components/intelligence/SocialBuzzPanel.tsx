import React, { useMemo } from 'react'
import clsx from 'clsx'
import { useNews } from '@/hooks/useNews'

// ── Types ────────────────────────────────────────────────────────────────────

export interface SocialTicker {
  id: string
  ticker: string
  mentionCount: number
  mentionChangePct: number
  sentimentScore: number  // 0–100 (0 = max bear, 50 = neutral, 100 = max bull)
  wsbAlert: boolean
}

export interface TrendingKeyword {
  id: string
  keyword: string
  count: number
  sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
}

/**
 * Props for SocialBuzzPanel.
 * @prop tickers  - Ranked tickers by mention count.
 * @prop keywords - Trending keywords/hashtags.
 * @prop loading  - Show skeleton loading state.
 */
export interface SocialBuzzPanelProps {
  tickers?: SocialTicker[]
  keywords?: TrendingKeyword[]
  loading?: boolean
}

// ── Sentiment gauge ───────────────────────────────────────────────────────────

function SentimentGauge({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score))
  // gradient: red → orange → green
  const bearW = Math.max(0, 50 - clamped)  // red portion
  const bullW = Math.max(0, clamped - 50)  // green portion
  const neutralW = 100 - bearW - bullW

  const label =
    clamped >= 65 ? 'BULL' :
    clamped <= 35 ? 'BEAR' : 'NEUTRAL'

  const labelColor =
    clamped >= 65 ? 'text-positive' :
    clamped <= 35 ? 'text-negative' : 'text-text-muted'

  return (
    <div className="flex items-center gap-1.5 flex-1 min-w-0">
      {/* Gauge bar */}
      <div className="flex h-1.5 flex-1 overflow-hidden">
        <div className="bg-negative h-full" style={{ width: `${bearW}%` }} />
        <div className="bg-text-muted h-full opacity-30" style={{ width: `${neutralW}%` }} />
        <div className="bg-positive h-full" style={{ width: `${bullW}%` }} />
      </div>
      <span className={clsx('font-mono text-[0.5rem] font-semibold flex-shrink-0 w-12 text-right', labelColor)}>
        {label} {clamped}
      </span>
    </div>
  )
}

// ── Volume bar ────────────────────────────────────────────────────────────────

function VolumeBar({ count, max }: { count: number; max: number }) {
  const pct = max > 0 ? (count / max) * 100 : 0
  return (
    <div className="h-1 bg-bg-panel-raised flex-1 overflow-hidden">
      <div className="h-full bg-accent-cyan opacity-50" style={{ width: `${pct}%` }} />
    </div>
  )
}

// ── WSB alert badge ───────────────────────────────────────────────────────────

function WsbBadge() {
  return (
    <span className="font-mono text-[0.48rem] px-1 py-px rounded-sm bg-warning-bg text-warning border border-warning-dim font-bold animate-pulse flex-shrink-0">
      WSB ↑
    </span>
  )
}

// ── Trending keyword badge ────────────────────────────────────────────────────

const KW_STYLE: Record<TrendingKeyword['sentiment'], string> = {
  BULLISH: 'text-positive border-positive-dim bg-positive-bg',
  BEARISH: 'text-negative border-negative-dim bg-negative-bg',
  NEUTRAL: 'text-text-secondary border-border-subtle bg-bg-panel-raised',
}

// ── Main component ────────────────────────────────────────────────────────────

export default function SocialBuzzPanel({
  tickers: propTickers,
  keywords: propKeywords,
  loading: propLoading = false,
}: SocialBuzzPanelProps) {
  const { data: newsItems = [], isLoading: fetchLoading } = useNews()
  const loading = propLoading || fetchLoading

  const { liveTickers, liveKeywords } = useMemo(() => {
    // Aggregate by ticker
    const tickerMap: Record<string, { bullish: number; bearish: number; neutral: number; count: number }> = {}
    newsItems.forEach(n => {
      const t = n.ticker
      if (!tickerMap[t]) tickerMap[t] = { bullish: 0, bearish: 0, neutral: 0, count: 0 }
      tickerMap[t].count++
      if (n.sentiment === 'BULLISH') tickerMap[t].bullish++
      else if (n.sentiment === 'BEARISH') tickerMap[t].bearish++
      else tickerMap[t].neutral++
    })

    const liveTickers: SocialTicker[] = Object.entries(tickerMap)
      .sort((a, b) => b[1].count - a[1].count)
      .map(([ticker, counts], idx) => {
        const total = counts.bullish + counts.bearish + counts.neutral
        const sentimentScore = total > 0
          ? Math.round(50 + ((counts.bullish - counts.bearish) / total) * 50)
          : 50
        return {
          id: `st-${idx}`,
          ticker,
          mentionCount: counts.count,
          mentionChangePct: 0,
          sentimentScore,
          wsbAlert: false,
        }
      })

    // Derive keywords from tickers: use $TICKER format for bullish/bearish ones
    const liveKeywords: TrendingKeyword[] = liveTickers.slice(0, 6).map((t, i) => ({
      id: `kw-${i}`,
      keyword: `$${t.ticker}`,
      count: t.mentionCount,
      sentiment: t.sentimentScore >= 60 ? 'BULLISH' : t.sentimentScore <= 40 ? 'BEARISH' : 'NEUTRAL',
    }))

    return { liveTickers, liveKeywords }
  }, [newsItems])

  const tickers = propTickers ?? liveTickers
  const keywords = propKeywords ?? liveKeywords
  const maxMentions = Math.max(...tickers.map(t => t.mentionCount), 1)

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header"><span>◈ Social Buzz</span></div>
        <div className="p-2 space-y-1">
          {Array.from({ length: 8 }).map((_, i) => <div key={i} className="h-6 skeleton rounded-sm" />)}
        </div>
      </div>
    )
  }

  if (!tickers.length) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="panel-header"><span className="flex-1">◈ Social Buzz</span></div>
        <div className="flex items-center justify-center flex-1 text-text-muted font-mono text-[0.65rem]">
          <div className="text-center">
            <div className="text-text-dim mb-1">NO DATA</div>
            <div className="text-[0.55rem]">Pending backend integration</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Social Buzz</span>
        <span className="font-mono text-[0.52rem] text-text-muted">{tickers.length} tickers</span>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        {/* Top tickers section */}
        <div className="px-2.5 pt-2 pb-1">
          <span className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest">
            Top by Mentions
          </span>
        </div>

        {/* Ticker rows */}
        <div>
          {tickers.map((t, idx) => {
            const changeUp = t.mentionChangePct > 0
            return (
              <div
                key={t.id}
                className="flex items-center gap-2 px-2.5 py-1.5 border-b border-border-muted hover:bg-bg-panel-hover transition-colors"
              >
                {/* Rank */}
                <span className="font-mono text-[0.55rem] text-text-muted w-4 flex-shrink-0 tabular-nums">
                  {idx + 1}
                </span>

                {/* Ticker */}
                <span className="font-mono text-[0.7rem] font-bold text-accent-cyan w-10 flex-shrink-0">
                  {t.ticker}
                </span>

                {/* WSB alert */}
                {t.wsbAlert && <WsbBadge />}

                {/* Volume bar */}
                <VolumeBar count={t.mentionCount} max={maxMentions} />

                {/* Mention count */}
                <span className="font-mono text-[0.6rem] text-text-secondary tabular-nums flex-shrink-0 w-14 text-right">
                  {t.mentionCount >= 1000 ? `${(t.mentionCount / 1000).toFixed(1)}K` : t.mentionCount}
                </span>

                {/* Change indicator */}
                <span className={clsx(
                  'font-mono text-[0.58rem] tabular-nums flex-shrink-0 w-14 text-right',
                  changeUp ? 'text-positive' : 'text-negative',
                )}>
                  {changeUp ? '▲' : '▼'} {Math.abs(t.mentionChangePct)}%
                </span>
              </div>
            )
          })}
        </div>

        {/* Sentiment gauges section */}
        <div className="px-2.5 pt-3 pb-1 border-t border-border-subtle">
          <span className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest">
            Sentiment Gauge
          </span>
        </div>

        <div>
          {tickers.map(t => (
            <div
              key={`g-${t.id}`}
              className="flex items-center gap-2 px-2.5 py-1 border-b border-border-muted"
            >
              <span className="font-mono text-[0.65rem] font-bold text-accent-cyan w-10 flex-shrink-0">
                {t.ticker}
              </span>
              <span className="font-mono text-[0.52rem] text-text-muted flex-shrink-0 w-6">BEAR</span>
              <SentimentGauge score={t.sentimentScore} />
              <span className="font-mono text-[0.52rem] text-text-muted flex-shrink-0 w-6">BULL</span>
            </div>
          ))}
        </div>

        {/* Trending keywords section */}
        <div className="px-2.5 pt-3 pb-1 border-t border-border-subtle">
          <span className="font-mono text-[0.52rem] text-text-muted uppercase tracking-widest">
            Trending Keywords
          </span>
        </div>

        <div className="flex flex-wrap gap-1.5 px-2.5 py-2">
          {keywords.map(kw => (
            <div key={kw.id} className="flex items-center gap-1">
              <span className={clsx(
                'font-mono text-[0.58rem] px-2 py-0.5 rounded-sm border',
                KW_STYLE[kw.sentiment],
              )}>
                {kw.keyword}
              </span>
              <span className="font-mono text-[0.52rem] text-text-muted tabular-nums">
                {kw.count >= 1000 ? `${(kw.count / 1000).toFixed(1)}K` : kw.count}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

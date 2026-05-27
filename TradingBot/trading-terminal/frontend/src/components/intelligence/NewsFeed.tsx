import React, { useState, useRef, useEffect } from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { useNews } from '@/hooks/useNews'
import type { NewsItem as ApiNewsItem } from '@/hooks/useNews'

// ── Types ────────────────────────────────────────────────────────────────────

type NewsSentiment = 'BULLISH' | 'BEARISH' | 'NEUTRAL'
type NewsSource = 'Reuters' | 'Bloomberg' | 'SEC' | 'Twitter' | 'Reddit' | 'CNBC'

export interface NewsItem {
  id: string
  ticker: string
  headline: string
  summary: string
  source: NewsSource
  time: Date
  sentiment: NewsSentiment
  relatedTickers: string[]
  url?: string
}

type SourceFilter = NewsSource | 'All'

/**
 * Props for NewsFeed.
 * @prop items   - News items to display.
 * @prop loading - Show skeleton loading state.
 */
export interface NewsFeedProps {
  items?: NewsItem[]
  loading?: boolean
}

// ── Sentiment badge ───────────────────────────────────────────────────────────

const SENTIMENT_STYLE: Record<NewsSentiment, string> = {
  BULLISH: 'text-positive border-positive-dim bg-positive-bg',
  BEARISH: 'text-negative border-negative-dim bg-negative-bg',
  NEUTRAL: 'text-text-secondary border-border-subtle bg-bg-panel-raised',
}

function SentimentBadge({ sentiment }: { sentiment: NewsSentiment }) {
  return (
    <span className={clsx('font-mono text-[0.5rem] px-1 py-px border rounded-sm font-semibold', SENTIMENT_STYLE[sentiment])}>
      {sentiment}
    </span>
  )
}

// ── Source badge ─────────────────────────────────────────────────────────────

const SOURCE_COLORS: Record<NewsSource, string> = {
  Reuters:  'text-text-muted',
  Bloomberg:'text-accent-cyan',
  SEC:      'text-warning',
  Twitter:  'text-info',
  Reddit:   'text-accent-cyan',
  CNBC:     'text-accent-amber',
}

// ── News item row ─────────────────────────────────────────────────────────────

function NewsRow({ item, expanded, onToggle }: { item: NewsItem; expanded: boolean; onToggle: () => void }) {
  const ago = formatDistanceToNow(item.time, { addSuffix: true })
  return (
    <div
      className={clsx(
        'border-b border-border-muted cursor-pointer transition-colors',
        expanded ? 'bg-[rgba(255,102,0,0.03)]' : 'hover:bg-bg-panel-hover',
      )}
      onClick={onToggle}
    >
      {/* Line 1 */}
      <div className="flex items-center gap-1.5 px-2.5 pt-2 pb-0.5">
        <span className="font-mono text-[0.65rem] font-bold text-accent-cyan flex-shrink-0 w-12">
          {item.ticker}
        </span>
        <SentimentBadge sentiment={item.sentiment} />
        <span className={clsx('font-mono text-[0.55rem] flex-shrink-0', SOURCE_COLORS[item.source])}>
          {item.source}
        </span>
        <div className="flex-1" />
        <span className="font-mono text-[0.52rem] text-text-muted flex-shrink-0">{ago}</span>
      </div>

      {/* Line 2 - headline */}
      <div className="px-2.5 pb-2">
        <p className={clsx('font-mono text-[0.63rem] leading-relaxed', expanded ? 'text-text-primary' : 'text-text-secondary truncate')}>
          {item.headline}
        </p>
      </div>

      {/* Expanded: summary + related tickers */}
      {expanded && (
        <div className="px-2.5 pb-3 border-t border-border-subtle bg-bg-panel-raised">
          <p className="font-mono text-[0.62rem] text-text-secondary leading-relaxed mt-2">
            {item.summary}
          </p>
          {item.relatedTickers.length > 0 && (
            <div className="flex items-center gap-1.5 mt-2">
              <span className="font-mono text-[0.52rem] text-text-muted">Related:</span>
              {item.relatedTickers.map(t => (
                <span key={t} className="font-mono text-[0.55rem] text-accent-cyan bg-bg-panel border border-border-subtle px-1 py-px rounded-sm">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

function mapApiItem(n: ApiNewsItem): NewsItem {
  return {
    id: n.id,
    ticker: n.ticker,
    headline: n.headline,
    summary: n.summary,
    source: (n.source as NewsSource) ?? 'Reuters',
    time: new Date(n.timestamp * 1000),
    sentiment: n.sentiment ?? 'NEUTRAL',
    relatedTickers: n.relatedTickers ?? [],
    url: n.url,
  }
}

export default function NewsFeed({
  items: propItems,
  loading: propLoading = false,
}: NewsFeedProps) {
  const { data: fetchedItems = [], isLoading: fetchLoading } = useNews()
  const loading = propLoading || fetchLoading
  const items: NewsItem[] = propItems ?? fetchedItems.map(mapApiItem)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('All')
  const [tickerFilter, setTickerFilter] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const sources: NewsSource[] = ['Reuters', 'Bloomberg', 'SEC', 'Twitter', 'Reddit']

  const filtered = items.filter(item => {
    if (sourceFilter !== 'All' && item.source !== sourceFilter) return false
    if (tickerFilter && !item.ticker.toLowerCase().includes(tickerFilter.toLowerCase())) return false
    return true
  })

  // Scroll to top when new items arrive
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [items.length])

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header"><span>◈ News Feed</span></div>
        <div className="p-2 space-y-1.5">
          {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-10 skeleton rounded-sm" />)}
        </div>
      </div>
    )
  }

  if (!items.length) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="panel-header"><span className="flex-1">◈ News Feed</span></div>
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
        <span className="flex-1">◈ News Feed</span>
        <span className="font-mono text-[0.52rem] text-text-muted">{filtered.length} items</span>
      </div>

      {/* Source filter pills */}
      <div className="flex items-center gap-1 px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0 flex-wrap">
        {(['All', ...sources] as SourceFilter[]).map(src => (
          <button
            key={src}
            onClick={() => setSourceFilter(src)}
            className={clsx(
              'font-mono text-[0.58rem] px-2 py-0.5 rounded-sm border transition-colors',
              sourceFilter === src
                ? 'bg-[rgba(255,102,0,0.1)] text-accent-cyan border-accent-cyan'
                : 'text-text-muted border-border-muted hover:border-border-subtle',
            )}
          >
            {src}
          </button>
        ))}
      </div>

      {/* Ticker search */}
      <div className="px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0">
        <input
          className="terminal-input text-[0.65rem]"
          placeholder="Filter by ticker..."
          value={tickerFilter}
          onChange={e => setTickerFilter(e.target.value)}
        />
      </div>

      {/* News list */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0">
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <span className="font-mono text-[0.65rem] text-text-muted">No news matching filter</span>
          </div>
        ) : (
          filtered.map(item => (
            <NewsRow
              key={item.id}
              item={item}
              expanded={expandedId === item.id}
              onToggle={() => setExpandedId(expandedId === item.id ? null : item.id)}
            />
          ))
        )}
      </div>
    </div>
  )
}

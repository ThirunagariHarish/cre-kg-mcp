import React, { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { ArrowUpCircle, ArrowDownCircle, MinusCircle } from 'lucide-react'
import type { Signal, SignalDirection, SignalSource } from '@/types/signals'
import SignalCard from './SignalCard'

const DIR_CONFIG: Record<SignalDirection, { bg: string; text: string; label: string }> = {
  BUY:   { bg: 'bg-positive-bg border-positive-dim', text: 'text-positive', label: 'BUY'   },
  SELL:  { bg: 'bg-negative-bg border-negative-dim', text: 'text-negative', label: 'SELL'  },
  HOLD:  { bg: 'bg-warning-bg   border-warning-dim',  text: 'text-warning',  label: 'HOLD'  },
  WATCH: { bg: 'bg-info-bg      border-info-dim',      text: 'text-info',     label: 'WATCH' },
}

interface SignalRowProps {
  signal: Signal
  selected: boolean
  onSelect: () => void
}

function SignalRow({ signal, selected, onSelect }: SignalRowProps) {
  const d = DIR_CONFIG[signal.direction]
  const ago = formatDistanceToNow(signal.receivedAt, { addSuffix: true })

  return (
    <div
      className={clsx(
        'flex items-center gap-2 px-2.5 py-2 cursor-pointer border-b border-border-muted group transition-colors',
        selected ? 'bg-[rgba(255,102,0,0.06)]' : 'hover:bg-bg-panel-hover'
      )}
      onClick={onSelect}
    >
      {/* Source */}
      <span className="font-mono text-[0.55rem] text-text-muted bg-bg-panel-raised border border-border-subtle px-1 py-px rounded-sm flex-shrink-0 uppercase">
        {signal.source.slice(0, 4)}
      </span>

      {/* Direction */}
      <span className={clsx('font-mono text-[0.6rem] font-semibold px-1.5 py-px border rounded-sm flex-shrink-0', d.bg, d.text)}>
        {d.label}
      </span>

      {/* Ticker */}
      <span className="font-mono text-[0.72rem] font-bold text-accent-cyan tracking-wide flex-shrink-0 w-12">
        {signal.ticker}
      </span>

      {/* Message */}
      <span className="flex-1 font-mono text-[0.6rem] text-text-secondary truncate">
        {signal.rawMessage.slice(0, 60)}
      </span>

      {/* Confidence */}
      {signal.confidence !== undefined && (
        <span className={clsx('font-mono text-[0.62rem] flex-shrink-0 tabular-nums',
          signal.confidence >= 70 ? 'text-positive' : signal.confidence >= 40 ? 'text-warning' : 'text-text-muted'
        )}>
          {signal.confidence}%
        </span>
      )}

      {/* Time */}
      <span className="font-mono text-[0.55rem] text-text-muted flex-shrink-0 hidden 2xl:block">{ago}</span>
    </div>
  )
}

interface SignalFeedProps {
  signals: Signal[]
  onSignalSelect?: (signal: Signal) => void
  onAnalyzeSignal?: (signal: Signal) => void
  selectedSignalId?: string
  loading?: boolean
}

export default function SignalFeed({
  signals,
  onSignalSelect,
  onAnalyzeSignal,
  selectedSignalId,
  loading = false,
}: SignalFeedProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [filterDir, setFilterDir] = useState<SignalDirection | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    if (autoScroll && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [signals, autoScroll])

  const handleScroll = () => {
    if (!scrollRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    setAutoScroll(scrollTop + clientHeight >= scrollHeight - 20)
  }

  const filtered = signals.filter(s => !filterDir || s.direction === filterDir)

  if (loading) {
    return <div className="p-2 space-y-1">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-8 skeleton rounded-sm" />)}</div>
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Panel Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Signal Feed</span>
        <span className="font-mono text-[0.55rem] text-text-muted">{filtered.length} signals</span>
      </div>

      {/* Filter Bar */}
      <div className="flex items-center gap-1 px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0">
        {(['BUY', 'SELL', 'HOLD'] as SignalDirection[]).map(dir => {
          const d = DIR_CONFIG[dir]
          const active = filterDir === dir
          return (
            <button
              key={dir}
              onClick={() => setFilterDir(active ? null : dir)}
              className={clsx(
                'font-mono text-[0.6rem] px-2 py-0.5 rounded-sm border transition-colors',
                active ? `${d.bg} ${d.text} border-current` : 'text-text-muted border-border-muted hover:border-border-subtle'
              )}
            >
              {dir}
            </button>
          )
        })}
        <div className="flex-1" />
        {!autoScroll && filtered.length > 0 && (
          <button
            className="font-mono text-[0.55rem] text-accent-cyan hover:underline"
            onClick={() => { setAutoScroll(true); if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight }}
          >
            ↓ latest
          </button>
        )}
      </div>

      {/* Feed */}
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto min-h-0">
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <span className="font-mono text-[0.65rem] text-text-muted">
              {signals.length === 0 ? 'Waiting for signals...' : 'No signals match filter'}
            </span>
          </div>
        ) : (
          filtered.map(signal =>
            expandedId === signal.id ? (
              <SignalCard
                key={signal.id}
                signal={signal}
                expanded
                onCollapse={() => setExpandedId(null)}
                onExecute={() => {}}
                onDismiss={() => setExpandedId(null)}
                onAnalyze={() => onAnalyzeSignal?.(signal)}
              />
            ) : (
              <SignalRow
                key={signal.id}
                signal={signal}
                selected={signal.id === selectedSignalId}
                onSelect={() => { setExpandedId(signal.id); onSignalSelect?.(signal) }}
              />
            )
          )
        )}
      </div>
    </div>
  )
}

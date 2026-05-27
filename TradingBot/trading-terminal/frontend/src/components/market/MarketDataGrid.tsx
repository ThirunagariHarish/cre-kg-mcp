import React, { useState, useMemo } from 'react'
import clsx from 'clsx'
import { ArrowUp, ArrowDown, Minus } from 'lucide-react'
import type { Quote } from '@/types/market'
import PriceCell from './PriceCell'
import { formatNumber, formatVolume } from '@/utils/formatters'

interface Column {
  key: keyof Quote | 'actions'
  label: string
  align?: 'left' | 'right' | 'center'
  width?: string
  className?: string
}

const COLUMNS: Column[] = [
  { key: 'symbol', label: 'SYMBOL', align: 'left', width: '60px' },
  { key: 'last', label: 'LAST', align: 'right', width: '64px' },
  { key: 'change', label: 'CHG', align: 'right', width: '56px' },
  { key: 'changePercent', label: '%CHG', align: 'right', width: '52px' },
  { key: 'bid', label: 'BID', align: 'right', width: '60px' },
  { key: 'ask', label: 'ASK', align: 'right', width: '60px' },
  { key: 'volume', label: 'VOL', align: 'right', width: '64px' },
]

interface QuoteRowProps {
  quote: Quote
  previousQuote?: Quote
  selected: boolean
  onSelect: () => void
}

function QuoteRow({ quote, previousQuote, selected, onSelect }: QuoteRowProps) {
  const isUp = quote.change > 0
  const isDown = quote.change < 0
  const changeColor = isUp ? 'text-positive' : isDown ? 'text-negative' : 'text-text-secondary'

  return (
    <tr
      className={clsx(
        'cursor-pointer transition-colors',
        selected
          ? 'bg-[rgba(56,189,248,0.08)] hover:bg-[rgba(56,189,248,0.12)]'
          : 'hover:bg-bg-panel-hover'
      )}
      onClick={onSelect}
    >
      {/* Symbol */}
      <td className="pl-2 pr-1 py-1 text-left">
        <div className="flex items-center gap-1">
          {isUp ? (
            <ArrowUp size={8} className="text-positive flex-shrink-0" />
          ) : isDown ? (
            <ArrowDown size={8} className="text-negative flex-shrink-0" />
          ) : (
            <Minus size={8} className="text-text-muted flex-shrink-0" />
          )}
          <span className="font-mono text-[0.7rem] font-medium text-accent-cyan tracking-wide">
            {quote.symbol}
          </span>
        </div>
      </td>

      {/* Last Price */}
      <td className="px-1 py-1 text-right">
        <PriceCell
          value={quote.last}
          previousValue={previousQuote?.last}
          decimals={2}
        />
      </td>

      {/* Change */}
      <td className={clsx('px-1 py-1 text-right font-mono text-[0.7rem] tabular-nums', changeColor)}>
        {quote.change > 0 ? '+' : ''}{quote.change.toFixed(2)}
      </td>

      {/* % Change */}
      <td className={clsx('px-1 py-1 text-right font-mono text-[0.7rem] tabular-nums', changeColor)}>
        {quote.changePercent > 0 ? '+' : ''}{quote.changePercent.toFixed(2)}%
      </td>

      {/* Bid */}
      <td className="px-1 py-1 text-right font-mono text-[0.7rem] tabular-nums text-text-secondary">
        {quote.bid.toFixed(2)}
      </td>

      {/* Ask */}
      <td className="px-1 py-1 text-right font-mono text-[0.7rem] tabular-nums text-text-secondary">
        {quote.ask.toFixed(2)}
      </td>

      {/* Volume */}
      <td className="px-1 pr-2 py-1 text-right font-mono text-[0.7rem] tabular-nums text-text-secondary">
        {formatVolume(quote.volume)}
      </td>
    </tr>
  )
}

interface MarketDataGridProps {
  quotes: Quote[]
  previousQuotes?: Map<string, Quote>
  onSymbolSelect?: (symbol: string) => void
  selectedSymbol?: string
  loading?: boolean
  className?: string
}

export default function MarketDataGrid({
  quotes,
  previousQuotes,
  onSymbolSelect,
  selectedSymbol,
  loading = false,
  className,
}: MarketDataGridProps) {
  const [sortKey, setSortKey] = useState<keyof Quote>('symbol')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [filter, setFilter] = useState('')

  const handleSort = (key: keyof Quote) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const sortedFiltered = useMemo(() => {
    let result = [...quotes]

    if (filter) {
      const f = filter.toUpperCase()
      result = result.filter(q => q.symbol.includes(f) || q.name?.toUpperCase().includes(f))
    }

    result.sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      if (av === undefined || bv === undefined) return 0
      const cmp = typeof av === 'string'
        ? av.localeCompare(bv as string)
        : (av as number) - (bv as number)
      return sortDir === 'asc' ? cmp : -cmp
    })

    return result
  }, [quotes, sortKey, sortDir, filter])

  if (loading) {
    return (
      <div className="flex flex-col gap-0.5 p-2">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="h-6 skeleton rounded-sm" />
        ))}
      </div>
    )
  }

  return (
    <div className={clsx('flex flex-col h-full overflow-hidden', className)}>
      {/* Filter bar */}
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border-subtle flex-shrink-0">
        <input
          type="text"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Filter symbols..."
          className="terminal-input h-6 text-[0.65rem]"
        />
        <span className="font-mono text-[0.6rem] text-text-muted flex-shrink-0">
          {sortedFiltered.length}/{quotes.length}
        </span>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full border-collapse">
          <thead>
            <tr className="sticky top-0 bg-bg-panel z-raised">
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  className={clsx(
                    'py-1 font-mono text-[0.6rem] uppercase tracking-widest',
                    'text-text-muted border-b border-border-subtle',
                    'cursor-pointer hover:text-text-primary transition-colors select-none',
                    col.align === 'left' ? 'text-left pl-2' : 'text-right pr-1',
                    sortKey === col.key && 'text-accent-cyan'
                  )}
                  style={{ width: col.width }}
                  onClick={() => col.key !== 'actions' && handleSort(col.key as keyof Quote)}
                >
                  {col.label}
                  {sortKey === col.key && (
                    <span className="ml-0.5">{sortDir === 'asc' ? '↑' : '↓'}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedFiltered.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length} className="text-center py-8 text-text-muted font-mono text-xs">
                  {filter ? 'No symbols match filter' : 'No market data'}
                </td>
              </tr>
            ) : (
              sortedFiltered.map(quote => (
                <QuoteRow
                  key={quote.symbol}
                  quote={quote}
                  previousQuote={previousQuotes?.get(quote.symbol)}
                  selected={quote.symbol === selectedSymbol}
                  onSelect={() => onSymbolSelect?.(quote.symbol)}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

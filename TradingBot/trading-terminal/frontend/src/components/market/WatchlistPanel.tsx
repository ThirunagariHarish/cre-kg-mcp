import React, { useState } from 'react'
import clsx from 'clsx'
import { Plus, X, Search, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronRight } from 'lucide-react'
import type { WatchlistItem, Quote } from '@/types/market'
import ContextMenu, { useContextMenu, WATCHLIST_CONTEXT_ITEMS } from '@/components/shared/ContextMenu'

interface WatchlistRowProps {
  item: WatchlistItem
  quote?: Quote
  selected: boolean
  onSelect: () => void
  onRemove: () => void
  onContextMenu: (e: React.MouseEvent) => void
}

function WatchlistRow({ item, quote, selected, onSelect, onRemove, onContextMenu }: WatchlistRowProps) {
  const up = (quote?.changePercent ?? 0) > 0
  const down = (quote?.changePercent ?? 0) < 0

  return (
    <div
      className={clsx(
        'flex items-center gap-0 px-0 py-0 cursor-pointer group border-b border-border-muted',
        'transition-colors',
        selected ? 'bg-[rgba(255,102,0,0.07)]' : 'hover:bg-bg-panel-hover'
      )}
      onClick={onSelect}
      onContextMenu={onContextMenu}
    >
      {/* Selected indicator */}
      <div className={clsx('w-0.5 self-stretch flex-shrink-0', selected ? 'bg-accent-cyan' : 'bg-transparent')} />

      {/* Trend arrow */}
      <div className="w-5 flex items-center justify-center py-2 flex-shrink-0">
        {up ? (
          <span className="text-[0.6rem] text-positive">▲</span>
        ) : down ? (
          <span className="text-[0.6rem] text-negative">▼</span>
        ) : (
          <span className="text-[0.6rem] text-text-muted">—</span>
        )}
      </div>

      {/* Symbol */}
      <div className="flex-1 min-w-0 py-2 pr-1">
        <span className={clsx(
          'font-mono text-[0.72rem] font-semibold tracking-wide',
          selected ? 'text-accent-cyan' : 'text-text-primary'
        )}>
          {item.symbol}
        </span>
        {item.name && (
          <p className="font-mono text-[0.55rem] text-text-muted truncate leading-none mt-0.5">
            {item.name}
          </p>
        )}
      </div>

      {/* Price */}
      <div className="w-16 text-right py-2 pr-1 flex-shrink-0">
        {quote ? (
          <span className="font-mono text-[0.7rem] text-text-primary tabular-nums">
            {quote.last.toFixed(2)}
          </span>
        ) : (
          <span className="font-mono text-[0.6rem] text-text-muted">—</span>
        )}
      </div>

      {/* Change % */}
      <div className="w-14 text-right py-2 pr-2 flex-shrink-0">
        {quote ? (
          <span className={clsx(
            'font-mono text-[0.65rem] tabular-nums',
            up ? 'text-positive' : down ? 'text-negative' : 'text-text-muted'
          )}>
            {up ? '+' : ''}{quote.changePercent.toFixed(2)}%
          </span>
        ) : null}
      </div>

      {/* Remove */}
      <button
        className="opacity-0 group-hover:opacity-100 mr-1 p-0.5 text-text-muted hover:text-negative rounded-sm transition-all"
        onClick={e => { e.stopPropagation(); onRemove() }}
      >
        <X size={8} />
      </button>
    </div>
  )
}

interface WatchlistPanelProps {
  items: WatchlistItem[]
  quotes: Map<string, Quote>
  selectedSymbol?: string
  onSymbolSelect?: (symbol: string) => void
  onAddSymbol?: (symbol: string) => void
  onRemoveSymbol?: (symbol: string) => void
}

export default function WatchlistPanel({
  items,
  quotes,
  selectedSymbol,
  onSymbolSelect,
  onAddSymbol,
  onRemoveSymbol,
}: WatchlistPanelProps) {
  const [search, setSearch] = useState('')
  const [addInput, setAddInput] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(['Tech', 'ETFs', 'Watching']))
  const ctxMenu = useContextMenu()

  const grouped = items.reduce((acc, item) => {
    const g = item.group ?? 'Watching'
    if (!acc[g]) acc[g] = []
    acc[g].push(item)
    return acc
  }, {} as Record<string, WatchlistItem[]>)

  const filteredItems = search
    ? items.filter(i => i.symbol.toUpperCase().includes(search.toUpperCase()))
    : null

  const handleAdd = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && addInput.trim()) {
      onAddSymbol?.(addInput.trim().toUpperCase())
      setAddInput('')
      setShowAdd(false)
    } else if (e.key === 'Escape') {
      setAddInput('')
      setShowAdd(false)
    }
  }

  const toggleGroup = (name: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Panel Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Watchlist</span>
        <span className="font-mono text-[0.55rem] text-text-muted">{items.length}</span>
        <button
          onClick={() => setShowAdd(v => !v)}
          className="p-0.5 text-text-muted hover:text-accent-cyan transition-colors rounded-sm"
          title="Add symbol"
        >
          <Plus size={10} />
        </button>
      </div>

      {/* Search */}
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-b border-border-subtle flex-shrink-0 bg-bg-panel">
        <Search size={9} className="text-text-muted flex-shrink-0" />
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter..."
          className="flex-1 bg-transparent border-none outline-none font-mono text-[0.65rem] text-text-primary placeholder:text-text-muted"
        />
      </div>

      {/* Add input */}
      {showAdd && (
        <div className="px-2.5 py-1.5 border-b border-border-subtle bg-bg-panel-raised flex-shrink-0">
          <input
            autoFocus
            type="text"
            value={addInput}
            onChange={e => setAddInput(e.target.value.toUpperCase())}
            onKeyDown={handleAdd}
            placeholder="SYMBOL ↵"
            className="terminal-input h-6 text-[0.65rem] uppercase"
          />
        </div>
      )}

      {/* Column Headers */}
      <div className="flex items-center border-b border-border-subtle flex-shrink-0 bg-bg-panel">
        <div className="w-5 flex-shrink-0" />
        <div className="flex-1 py-1 pl-0">
          <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">Symbol</span>
        </div>
        <div className="w-16 text-right pr-1 flex-shrink-0">
          <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">Last</span>
        </div>
        <div className="w-14 text-right pr-2 flex-shrink-0">
          <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">%Chg</span>
        </div>
        <div className="w-5 flex-shrink-0" />
      </div>

      {/* Items */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {search ? (
          filteredItems?.map(item => (
            <WatchlistRow
              key={item.symbol}
              item={item}
              quote={quotes.get(item.symbol)}
              selected={item.symbol === selectedSymbol}
              onSelect={() => onSymbolSelect?.(item.symbol)}
              onRemove={() => onRemoveSymbol?.(item.symbol)}
              onContextMenu={e => ctxMenu.onOpen(e, WATCHLIST_CONTEXT_ITEMS(item.symbol, {
                onAddToTicket: () => {},
                onSetAlert: () => {},
                onViewChart: () => onSymbolSelect?.(item.symbol),
                onRemove: () => onRemoveSymbol?.(item.symbol),
              }))}
            />
          ))
        ) : (
          Object.entries(grouped).map(([groupName, groupItems]) => (
            <div key={groupName}>
              <button
                className="w-full flex items-center gap-1.5 px-2.5 py-1 hover:bg-bg-panel-raised transition-colors border-b border-border-muted"
                onClick={() => toggleGroup(groupName)}
              >
                <span className="text-text-muted flex-shrink-0">
                  {expandedGroups.has(groupName)
                    ? <ChevronDown size={8} />
                    : <ChevronRight size={8} />}
                </span>
                <span className="font-mono text-[0.58rem] text-text-muted uppercase tracking-widest flex-1 text-left">
                  {groupName}
                </span>
                <span className="font-mono text-[0.55rem] text-text-muted">{groupItems.length}</span>
              </button>

              {expandedGroups.has(groupName) && groupItems.map(item => (
                <WatchlistRow
                  key={item.symbol}
                  item={item}
                  quote={quotes.get(item.symbol)}
                  selected={item.symbol === selectedSymbol}
                  onSelect={() => onSymbolSelect?.(item.symbol)}
                  onRemove={() => onRemoveSymbol?.(item.symbol)}
                  onContextMenu={e => ctxMenu.onOpen(e, WATCHLIST_CONTEXT_ITEMS(item.symbol, {
                    onAddToTicket: () => {},
                    onSetAlert: () => {},
                    onViewChart: () => onSymbolSelect?.(item.symbol),
                    onRemove: () => onRemoveSymbol?.(item.symbol),
                  }))}
                />
              ))}
            </div>
          ))
        )}

        {items.length === 0 && (
          <div className="flex flex-col items-center justify-center h-32 gap-2">
            <span className="font-mono text-[0.65rem] text-text-muted">No symbols</span>
            <button
              className="font-mono text-[0.6rem] text-accent-cyan hover:underline"
              onClick={() => setShowAdd(true)}
            >
              + Add a symbol
            </button>
          </div>
        )}
      </div>

      <ContextMenu
        open={ctxMenu.open}
        position={ctxMenu.position}
        items={ctxMenu.items}
        onClose={ctxMenu.onClose}
      />
    </div>
  )
}

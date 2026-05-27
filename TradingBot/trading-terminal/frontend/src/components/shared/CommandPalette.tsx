import React, { useState, useEffect, useRef, useCallback } from 'react'
import clsx from 'clsx'
import * as Dialog from '@radix-ui/react-dialog'
import { Search, ChevronRight, Clock, TrendingUp, Shield, FileText, Activity } from 'lucide-react'
import { useTerminalStore } from '@/stores/terminalStore'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

interface CommandItem {
  id: string
  label: string
  description?: string
  category: 'symbol' | 'command' | 'navigation' | 'risk'
  icon: React.ReactNode
  shortcut?: string
  action: () => void
}

const CATEGORY_LABELS = {
  symbol: 'Symbols',
  command: 'Commands',
  navigation: 'Navigation',
  risk: 'Risk',
}

interface CommandPaletteProps {
  symbols?: string[]
}

export default function CommandPalette({ symbols = [] }: CommandPaletteProps) {
  const open = useTerminalStore(s => s.commandPaletteOpen)
  const setOpen = useTerminalStore(s => s.setCommandPaletteOpen)
  const commandHistory = useTerminalStore(s => s.commandHistory)
  const addCommandHistory = useTerminalStore(s => s.addCommandHistory)
  const setWorkspaceTab = useTerminalStore(s => s.setWorkspaceTab)

  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [searchResults, setSearchResults] = useState<any[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const search = useCallback(async (q: string) => {
    if (q.length < 1) { setSearchResults([]); return }
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const results = await apiGet<any[]>(API.marketSearch(q))
      setSearchResults(results ?? [])
    } catch {
      setSearchResults([])
    }
  }, [])

  const builtinCommands: CommandItem[] = [
    {
      id: 'nav-positions',
      label: 'View Positions',
      description: 'Open positions and P&L',
      category: 'navigation',
      icon: <TrendingUp size={12} />,
      shortcut: 'G P',
      action: () => { setWorkspaceTab('POSITIONS'); setOpen(false) },
    },
    {
      id: 'nav-agents',
      label: 'View Agents',
      description: 'Trading agent status',
      category: 'navigation',
      icon: <TrendingUp size={12} />,
      shortcut: 'G A',
      action: () => { setWorkspaceTab('AGENTS'); setOpen(false) },
    },
    {
      id: 'nav-signals',
      label: 'View Signals',
      description: 'Signal feed and analysis',
      category: 'navigation',
      icon: <TrendingUp size={12} />,
      shortcut: 'G S',
      action: () => { setWorkspaceTab('SIGNALS'); setOpen(false) },
    },
    {
      id: 'nav-orders',
      label: 'View Orders',
      description: 'Order blotter history',
      category: 'navigation',
      icon: <FileText size={12} />,
      shortcut: 'G O',
      action: () => { setWorkspaceTab('ORDERS'); setOpen(false) },
    },
    {
      id: 'nav-chart',
      label: 'View Chart',
      description: 'Candlestick chart with order book and options chain',
      category: 'navigation',
      icon: <Activity size={12} />,
      shortcut: 'G C',
      action: () => { setWorkspaceTab('CHART'); setOpen(false) },
    },
    {
      id: 'nav-analytics',
      label: 'View Analytics',
      description: 'Equity curve, drawdown, attribution and metrics',
      category: 'navigation',
      icon: <Activity size={12} />,
      shortcut: 'G N',
      action: () => { setWorkspaceTab('ANALYTICS'); setOpen(false) },
    },
    {
      id: 'nav-intelligence',
      label: 'View Intelligence',
      description: 'Market regime, confluence signals, news and flow',
      category: 'navigation',
      icon: <Activity size={12} />,
      shortcut: 'G I',
      action: () => { setWorkspaceTab('INTELLIGENCE'); setOpen(false) },
    },
    {
      id: 'nav-backtest',
      label: 'View Backtest',
      description: 'Run strategy backtests with P&L simulation',
      category: 'navigation',
      icon: <Activity size={12} />,
      shortcut: 'G B',
      action: () => { setWorkspaceTab('BACKTEST'); setOpen(false) },
    },
    {
      id: 'cmd-risk-status',
      label: 'Risk Status',
      description: 'View current risk metrics',
      category: 'risk',
      icon: <Shield size={12} />,
      action: () => { setOpen(false) },
    },
    {
      id: 'cmd-kill-switch',
      label: 'Kill Switch',
      description: 'Emergency trading halt',
      category: 'risk',
      icon: <Shield size={12} />,
      action: () => { setOpen(false) },
    },
  ]

  // Trigger live search when query changes
  useEffect(() => {
    if (query.length >= 1) {
      search(query)
    } else {
      setSearchResults([])
    }
  }, [query, search])

  // Symbol commands — prefer live search results when available, else fall back to prop list
  const searchSymbols: string[] = searchResults.length
    ? searchResults.map((r) => (typeof r === 'string' ? r : r.symbol ?? r.ticker ?? ''))
    : symbols
  const symbolCommands: CommandItem[] = searchSymbols.filter(Boolean).map(sym => ({
    id: `symbol-${sym}`,
    label: sym,
    description: `View ${sym} details`,
    category: 'symbol' as const,
    icon: <TrendingUp size={10} />,
    action: () => {
      addCommandHistory(`view ${sym}`)
      setOpen(false)
    },
  }))

  // Filter
  const q = query.toLowerCase().trim()
  const allCommands = [...symbolCommands, ...builtinCommands]

  const filtered = q
    ? allCommands.filter(c =>
        c.label.toLowerCase().includes(q) ||
        c.description?.toLowerCase().includes(q)
      )
    : builtinCommands.slice(0, 8)

  // Group by category
  const grouped = filtered.reduce((acc, item) => {
    if (!acc[item.category]) acc[item.category] = []
    acc[item.category].push(item)
    return acc
  }, {} as Record<string, CommandItem[]>)

  const flatItems = Object.values(grouped).flat()

  useEffect(() => {
    setActiveIndex(0)
  }, [query])

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50)
      setQuery('')
      setActiveIndex(0)
    }
  }, [open])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex(i => Math.min(i + 1, flatItems.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = flatItems[activeIndex]
      if (item) {
        addCommandHistory(item.label)
        item.action()
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  let flatIndex = 0

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/70 z-modal animate-fade-in" />
        <Dialog.Content
          className={clsx(
            'fixed left-1/2 top-[20%] -translate-x-1/2',
            'z-modal w-full max-w-lg',
            'bg-bg-panel border border-border-subtle rounded',
            'shadow-dropdown animate-slide-in-up',
            'overflow-hidden'
          )}
          onKeyDown={handleKeyDown}
        >
          <Dialog.Title className="sr-only">Command Palette</Dialog.Title>

          {/* Search input */}
          <div className="flex items-center gap-2.5 px-3 py-2.5 border-b border-border-subtle">
            <Search size={13} className="text-text-muted flex-shrink-0" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search symbols, commands, pages..."
              className="flex-1 bg-transparent border-none outline-none font-mono text-sm text-text-primary placeholder:text-text-muted"
            />
            <kbd className="font-mono text-[0.55rem] text-text-muted bg-bg-panel-raised px-1 py-0.5 rounded border border-border-subtle">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div
            ref={listRef}
            className="overflow-y-auto max-h-80"
          >
            {!q && commandHistory.length > 0 && (
              <div>
                <div className="px-3 py-1 border-b border-border-muted">
                  <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest flex items-center gap-1">
                    <Clock size={8} />
                    Recent
                  </span>
                </div>
                {commandHistory.slice(0, 3).map((cmd, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-bg-panel-raised text-text-muted hover:text-text-primary transition-colors"
                  >
                    <Clock size={10} className="flex-shrink-0" />
                    <span className="font-mono text-xs flex-1">{cmd}</span>
                    <ChevronRight size={10} />
                  </div>
                ))}
              </div>
            )}

            {Object.entries(grouped).map(([category, items]) => (
              <div key={category}>
                <div className="px-3 py-1 border-b border-border-muted">
                  <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">
                    {CATEGORY_LABELS[category as keyof typeof CATEGORY_LABELS] ?? category}
                  </span>
                </div>
                {items.map(item => {
                  const idx = flatIndex++
                  const isActive = idx === activeIndex
                  return (
                    <div
                      key={item.id}
                      className={clsx(
                        'flex items-center gap-2.5 px-3 py-2 cursor-pointer transition-colors',
                        isActive
                          ? 'bg-bg-panel-raised text-text-primary'
                          : 'hover:bg-bg-panel-hover text-text-secondary hover:text-text-primary'
                      )}
                      onClick={() => {
                        addCommandHistory(item.label)
                        item.action()
                      }}
                    >
                      <span className="flex-shrink-0 text-text-muted">{item.icon}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-medium truncate">{item.label}</span>
                          {item.description && (
                            <span className="font-mono text-[0.6rem] text-text-muted truncate">
                              — {item.description}
                            </span>
                          )}
                        </div>
                      </div>
                      {item.shortcut && (
                        <kbd className="font-mono text-[0.55rem] text-text-muted bg-bg-root px-1 py-0.5 rounded border border-border-subtle flex-shrink-0">
                          {item.shortcut}
                        </kbd>
                      )}
                      {isActive && <ChevronRight size={10} className="flex-shrink-0 text-accent-cyan" />}
                    </div>
                  )
                })}
              </div>
            ))}

            {filtered.length === 0 && (
              <div className="flex flex-col items-center justify-center py-8 gap-1">
                <span className="font-mono text-xs text-text-muted">No results for "{query}"</span>
                <span className="font-mono text-[0.6rem] text-text-muted">Try a symbol or command name</span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center gap-3 px-3 py-1.5 border-t border-border-subtle bg-bg-root">
            <span className="font-mono text-[0.55rem] text-text-muted flex items-center gap-1">
              <kbd className="bg-bg-panel-raised px-0.5 rounded border border-border-subtle">↑↓</kbd>
              Navigate
            </span>
            <span className="font-mono text-[0.55rem] text-text-muted flex items-center gap-1">
              <kbd className="bg-bg-panel-raised px-0.5 rounded border border-border-subtle">↵</kbd>
              Select
            </span>
            <span className="font-mono text-[0.55rem] text-text-muted flex items-center gap-1">
              <kbd className="bg-bg-panel-raised px-0.5 rounded border border-border-subtle">Esc</kbd>
              Close
            </span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

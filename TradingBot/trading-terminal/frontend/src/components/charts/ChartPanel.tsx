/**
 * ChartPanel — Master chart panel.
 * CandlestickChart (~70%) + optional right sidebar (OrderBookL2 or OptionsChain).
 * Sidebar toggle: BOOK | OPTIONS | HIDE.
 * Symbol input with ↵ to load. Ctrl+C keyboard hint.
 */

import React, { useState, useCallback, useRef, useEffect } from 'react'
import clsx from 'clsx'
import { CandlestickChart } from './CandlestickChart'
import { OrderBookL2 } from './OrderBookL2'
import { OptionsChain } from './OptionsChain'
import { useOhlcv } from '@/hooks/useOhlcv'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ChartPanelProps {
  defaultSymbol?: string
  onSymbolChange?: (s: string) => void
}

type SidebarMode = 'book' | 'options' | 'hide'

// ── Component ─────────────────────────────────────────────────────────────────

export function ChartPanel({ defaultSymbol = 'AAPL', onSymbolChange }: ChartPanelProps) {
  const [symbol, setSymbol] = useState(defaultSymbol)
  const [inputValue, setInputValue] = useState(defaultSymbol)
  const [sidebarMode, setSidebarMode] = useState<SidebarMode>('book')
  const [timeframe, setTimeframe] = useState('1h')
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: ohlcvBars = [], isLoading: chartLoading } = useOhlcv(symbol, timeframe)

  // Ctrl+C → focus chart input
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'c' && !e.shiftKey) {
        // Only intercept if not in an input already
        const active = document.activeElement
        if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return
        e.preventDefault()
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleSymbolSubmit = useCallback(() => {
    const trimmed = inputValue.trim().toUpperCase()
    if (trimmed && trimmed !== symbol) {
      setSymbol(trimmed)
      onSymbolChange?.(trimmed)
    }
  }, [inputValue, symbol, onSymbolChange])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') handleSymbolSubmit()
    },
    [handleSymbolSubmit],
  )

  const sidebarButtons: Array<{ mode: SidebarMode; label: string }> = [
    { mode: 'book', label: 'BOOK' },
    { mode: 'options', label: 'OPTIONS' },
    { mode: 'hide', label: 'HIDE' },
  ]

  return (
    <div className="flex flex-col h-full w-full bg-bg-root overflow-hidden">
      {/* Master panel header */}
      <div className="panel-header flex-shrink-0 gap-2">
        <span className="text-accent-cyan">◈ Market</span>

        {/* Symbol input */}
        <div className="flex items-center gap-1 ml-2">
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={e => setInputValue(e.target.value.toUpperCase())}
            onKeyDown={handleKeyDown}
            onBlur={handleSymbolSubmit}
            className={clsx(
              'terminal-input w-20 text-xs text-accent-cyan uppercase',
            )}
            placeholder="AAPL"
            maxLength={10}
            aria-label="Symbol"
            spellCheck={false}
          />
          <button
            onClick={handleSymbolSubmit}
            className="px-1.5 py-0.5 text-2xs font-mono border border-accent-cyan text-accent-cyan hover:bg-accent-cyan hover:text-bg-root rounded-sm transition-colors"
            aria-label="Load symbol"
          >
            ↵
          </button>
        </div>

        <span className="text-text-muted text-2xs ml-1">Ctrl+C to focus</span>

        {/* Timeframe display */}
        <span className="ml-2 text-text-muted text-2xs">{timeframe}</span>

        {/* Sidebar toggle */}
        <div className="ml-auto flex gap-0.5">
          {sidebarButtons.map(({ mode, label }) => (
            <button
              key={mode}
              onClick={() => setSidebarMode(mode)}
              className={clsx(
                'px-2 py-0.5 text-2xs font-mono border rounded-sm transition-colors',
                sidebarMode === mode
                  ? 'bg-accent-cyan text-bg-root border-accent-cyan'
                  : 'bg-transparent text-text-secondary border-border-subtle hover:border-accent-cyan hover:text-accent-cyan',
              )}
              aria-pressed={sidebarMode === mode}
            >
              [{label}]
            </button>
          ))}
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Main chart — 70% (or 100% when sidebar hidden) */}
        <div
          className={clsx(
            'flex-shrink-0 overflow-hidden border-r border-border-subtle transition-all duration-200',
            sidebarMode === 'hide' ? 'w-full border-r-0' : 'w-[70%]',
          )}
        >
          <CandlestickChart
            symbol={symbol}
            timeframe={timeframe}
            onTimeframeChange={setTimeframe}
            data={ohlcvBars}
            loading={chartLoading}
          />
        </div>

        {/* Right sidebar */}
        {sidebarMode !== 'hide' && (
          <div className="flex-1 min-w-0 overflow-hidden">
            {sidebarMode === 'book' && (
              <OrderBookL2 symbol={symbol} />
            )}
            {sidebarMode === 'options' && (
              <OptionsChain symbol={symbol} />
            )}
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className="flex-shrink-0 flex items-center gap-4 px-3 py-1 border-t border-border-subtle text-2xs font-mono text-text-muted">
        <span className="text-positive">
          <span className="status-dot status-dot--online mr-1" />
          LIVE
        </span>
        <span>{symbol}</span>
        <span className="text-accent-cyan">{timeframe}</span>
        <span className="ml-auto">
          {sidebarMode !== 'hide' && (
            <span className="text-text-muted">
              SIDEBAR: <span className="text-text-secondary">{sidebarMode.toUpperCase()}</span>
            </span>
          )}
        </span>
      </div>
    </div>
  )
}

export default ChartPanel

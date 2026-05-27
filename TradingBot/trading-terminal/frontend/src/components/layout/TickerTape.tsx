import React from 'react'
import clsx from 'clsx'

interface TickerItem {
  symbol: string
  price: number
  change: number
  changePct: number
}

const TICKER_DATA: TickerItem[] = [
  { symbol: 'AAPL',  price: 178.32, change:  1.23, changePct:  0.69 },
  { symbol: 'NVDA',  price: 891.50, change: 12.34, changePct:  1.40 },
  { symbol: 'TSLA',  price: 201.12, change: -3.45, changePct: -1.69 },
  { symbol: 'MSFT',  price: 416.78, change:  2.12, changePct:  0.51 },
  { symbol: 'AMD',   price: 178.92, change: -1.23, changePct: -0.68 },
  { symbol: 'META',  price: 503.12, change:  8.45, changePct:  1.71 },
  { symbol: 'GOOGL', price: 154.32, change:  0.87, changePct:  0.57 },
  { symbol: 'AMZN',  price: 182.91, change:  3.21, changePct:  1.79 },
  { symbol: 'SPY',   price: 523.40, change:  1.75, changePct:  0.34 },
  { symbol: 'QQQ',   price: 448.90, change:  2.98, changePct:  0.67 },
  { symbol: 'BRK.B', price: 403.55, change: -0.88, changePct: -0.22 },
  { symbol: 'JPM',   price: 196.72, change:  1.45, changePct:  0.74 },
  { symbol: 'GS',    price: 454.12, change: -2.34, changePct: -0.51 },
  { symbol: 'COIN',  price: 238.44, change: 11.23, changePct:  4.94 },
  { symbol: 'PLTR',  price:  24.87, change:  0.43, changePct:  1.76 },
]

function TickerCell({ item }: { item: TickerItem }) {
  const up = item.changePct >= 0
  return (
    <div className="flex items-center gap-2 px-4 border-r border-border-subtle flex-shrink-0">
      <span className="font-mono text-[0.65rem] font-semibold text-accent-cyan tracking-wider">
        {item.symbol}
      </span>
      <span className="font-mono text-[0.65rem] text-text-primary tabular-nums">
        {item.price.toFixed(2)}
      </span>
      <span className={clsx(
        'font-mono text-[0.6rem] tabular-nums',
        up ? 'text-positive' : 'text-negative'
      )}>
        {up ? '▲' : '▼'}{' '}
        {up ? '+' : ''}{item.change.toFixed(2)}{' '}
        ({up ? '+' : ''}{item.changePct.toFixed(2)}%)
      </span>
    </div>
  )
}

export default function TickerTape() {
  const doubled = [...TICKER_DATA, ...TICKER_DATA]

  return (
    <div className="flex items-center h-6 bg-bg-root border-b border-border-subtle flex-shrink-0 overflow-hidden select-none">
      <div className="ticker-scroll flex items-center h-full whitespace-nowrap">
        {doubled.map((item, i) => (
          <TickerCell key={`${item.symbol}-${i}`} item={item} />
        ))}
      </div>
    </div>
  )
}

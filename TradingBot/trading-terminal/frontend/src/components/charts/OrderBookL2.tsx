/**
 * OrderBookL2 — Level 2 order book depth ladder.
 * Top 10 bids (green) + top 10 asks (red), mid-price, depth bars, flash animation.
 * Updates every 500ms in mock mode.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface OrderBookL2Props {
  symbol?: string
  /** [price, size] pairs — bids sorted descending by price */
  bids?: Array<[number, number]>
  /** [price, size] pairs — asks sorted ascending by price */
  asks?: Array<[number, number]>
  loading?: boolean
}

type Level = { price: number; size: number; cumSize: number }

// ── Mock data generator ───────────────────────────────────────────────────────

function generateL2(mid: number): { bids: Array<[number, number]>; asks: Array<[number, number]> } {
  const tickSize = mid > 1000 ? 0.5 : mid > 100 ? 0.1 : 0.01
  const bids: Array<[number, number]> = []
  const asks: Array<[number, number]> = []
  for (let i = 1; i <= 12; i++) {
    const bidPx = parseFloat((mid - i * tickSize).toFixed(2))
    const askPx = parseFloat((mid + i * tickSize).toFixed(2))
    bids.push([bidPx, Math.round(100 + Math.random() * 2000)])
    asks.push([askPx, Math.round(100 + Math.random() * 2000)])
  }
  return { bids, asks }
}

function perturbL2(
  prev: Array<[number, number]>,
  mid: number,
  isBid: boolean,
): Array<[number, number]> {
  return prev.map(([px, sz]) => {
    const newSz = Math.max(50, sz + Math.round((Math.random() - 0.5) * 300))
    // randomly refresh a price level
    const refresh = Math.random() < 0.1
    const tickSize = mid > 1000 ? 0.5 : mid > 100 ? 0.1 : 0.01
    if (refresh) {
      const offset = (isBid ? -1 : 1) * (px === 0 ? 1 : Math.abs(px - mid) / tickSize) * tickSize
      return [parseFloat((mid + offset).toFixed(2)) as number, newSz] as [number, number]
    }
    return [px, newSz] as [number, number]
  })
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildLevels(pairs: Array<[number, number]>, topN = 10): Level[] {
  const levels: Level[] = []
  let cum = 0
  for (let i = 0; i < Math.min(topN, pairs.length); i++) {
    cum += pairs[i][1]
    levels.push({ price: pairs[i][0], size: pairs[i][1], cumSize: cum })
  }
  return levels
}

const fmtPx = (v: number) => v.toFixed(v > 1000 ? 1 : v > 100 ? 2 : 4)
const fmtSz = (v: number) => {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`
  return v.toString()
}

// ── Row component ─────────────────────────────────────────────────────────────

interface BookRowProps {
  level: Level
  maxCum: number
  side: 'bid' | 'ask'
  prevSize?: number
}

function BookRow({ level, maxCum, side, prevSize }: BookRowProps) {
  const barPct = maxCum > 0 ? (level.cumSize / maxCum) * 100 : 0
  const isBid = side === 'bid'
  const barBg = isBid ? 'rgba(0,230,118,0.12)' : 'rgba(255,23,68,0.12)'
  const priceColor = isBid ? 'text-positive' : 'text-negative'

  const changed = prevSize !== undefined && prevSize !== level.size
  const flashed = changed && level.size > (prevSize ?? 0)

  return (
    <div
      className={clsx(
        'relative flex items-center px-1.5 h-5 text-2xs font-mono tabular-nums select-none',
        'border-b border-[#0c0c0c] hover:bg-bg-panel-hover transition-colors',
        flashed ? 'price-flash-up' : changed ? 'price-flash-down' : '',
      )}
      style={{ minHeight: '20px' }}
    >
      {/* Depth bar */}
      <div
        className="absolute inset-y-0 pointer-events-none"
        style={{
          [isBid ? 'right' : 'left']: 0,
          width: `${barPct}%`,
          background: barBg,
        }}
      />
      {/* Price */}
      <span className={clsx('flex-1 z-10 font-bold', priceColor)}>
        {fmtPx(level.price)}
      </span>
      {/* Size */}
      <span className="z-10 text-text-secondary w-14 text-right">{fmtSz(level.size)}</span>
      {/* Cumulative */}
      <span className="z-10 text-text-muted w-14 text-right">{fmtSz(level.cumSize)}</span>
    </div>
  )
}

// ── Column header ─────────────────────────────────────────────────────────────

function ColHeader({ side }: { side: 'bid' | 'ask' }) {
  const isBid = side === 'bid'
  return (
    <div
      className={clsx(
        'flex items-center px-1.5 h-5 text-2xs font-mono uppercase tracking-wider border-b border-border-subtle',
        isBid ? 'text-positive' : 'text-negative',
      )}
    >
      <span className="flex-1">{isBid ? 'BID' : 'ASK'}</span>
      <span className="w-14 text-right text-text-muted">SIZE</span>
      <span className="w-14 text-right text-text-muted">CUM</span>
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OrderBookL2({ symbol = 'AAPL', bids, asks, loading = false }: OrderBookL2Props) {
  const [mockBids, setMockBids] = useState<Array<[number, number]>>([])
  const [mockAsks, setMockAsks] = useState<Array<[number, number]>>([])
  const prevBidSizes = useRef<Map<number, number>>(new Map())
  const prevAskSizes = useRef<Map<number, number>>(new Map())
  const isMock = !bids && !asks

  const { data: quoteData } = useQuery({
    queryKey: ['quote-for-orderbook', symbol],
    queryFn: () => apiGet<any>(API.quote(symbol ?? '')),
    enabled: !!symbol && !bids && !asks,
    refetchInterval: 5_000,
  })
  const liveMid = quoteData?.price ?? quoteData?.last ?? 185.5

  // Initialize mock data
  useEffect(() => {
    if (!isMock) return
    const { bids: b, asks: a } = generateL2(liveMid)
    setMockBids(b)
    setMockAsks(a)
  }, [isMock, liveMid])

  // Mock update loop
  useEffect(() => {
    if (!isMock) return
    const timer = setInterval(() => {
      setMockBids(prev => {
        if (prev.length === 0) return prev
        return perturbL2(prev, liveMid, true)
      })
      setMockAsks(prev => {
        if (prev.length === 0) return prev
        return perturbL2(prev, liveMid, false)
      })
    }, 500)
    return () => clearInterval(timer)
  }, [isMock, liveMid])

  const activeBids = bids ?? mockBids
  const activeAsks = asks ?? mockAsks

  const bidLevels = buildLevels(activeBids)
  const askLevels = buildLevels(activeAsks)

  const maxBidCum = bidLevels.length > 0 ? bidLevels[bidLevels.length - 1].cumSize : 1
  const maxAskCum = askLevels.length > 0 ? askLevels[askLevels.length - 1].cumSize : 1

  const bestBid = activeBids[0]?.[0] ?? 0
  const bestAsk = activeAsks[0]?.[0] ?? 0
  const midPrice = bestBid > 0 && bestAsk > 0 ? (bestBid + bestAsk) / 2 : liveMid
  const spread = bestAsk - bestBid
  const spreadPct = bestBid > 0 ? (spread / bestBid) * 100 : 0

  // Track previous sizes for flash
  const getPrevBidSize = useCallback((price: number) => prevBidSizes.current.get(price), [])
  const getPrevAskSize = useCallback((price: number) => prevAskSizes.current.get(price), [])

  useEffect(() => {
    bidLevels.forEach(l => prevBidSizes.current.set(l.price, l.size))
    askLevels.forEach(l => prevAskSizes.current.set(l.price, l.size))
  })

  return (
    <div className="flex flex-col h-full w-full bg-bg-panel overflow-hidden">
      {/* Panel header */}
      <div className="panel-header flex-shrink-0">
        <span className="text-accent-cyan">◈ Order Book</span>
        <span className="text-text-secondary ml-2">{symbol}</span>
        <span className="text-text-muted ml-2">|</span>
        <span className="text-text-muted ml-2 text-2xs">SPREAD</span>
        <span className="text-text-primary ml-1 tabular-nums">{spread.toFixed(2)}</span>
        <span className="text-text-muted ml-1 tabular-nums">({spreadPct.toFixed(3)}%)</span>
      </div>

      {loading && (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-accent-cyan text-xs font-mono animate-pulse">LOADING…</span>
        </div>
      )}

      {!loading && (
        <div className="flex-1 overflow-hidden min-h-0 flex flex-col">
          {/* Column headers */}
          <div className="flex-shrink-0 grid grid-cols-2 border-b border-border-subtle">
            <ColHeader side="bid" />
            <ColHeader side="ask" />
          </div>

          {/* Ask side (top — sorted descending so best ask is nearest mid) */}
          <div className="flex-shrink-0 overflow-hidden">
            {[...askLevels].reverse().map(level => (
              <BookRow
                key={`ask-${level.price}`}
                level={level}
                maxCum={maxAskCum}
                side="ask"
                prevSize={getPrevAskSize(level.price)}
              />
            ))}
          </div>

          {/* Mid price row */}
          <div className="flex-shrink-0 flex items-center justify-between px-2 h-7 bg-bg-panel-raised border-y border-[rgba(255,102,0,0.3)]">
            <span className="text-text-muted text-2xs font-mono">MID</span>
            <span className="text-accent-cyan text-sm font-mono font-bold tabular-nums">
              {fmtPx(midPrice)}
            </span>
            <span className="text-text-muted text-2xs font-mono">
              SPR {spread.toFixed(2)}
            </span>
          </div>

          {/* Bid side (sorted descending, best bid at top nearest mid) */}
          <div className="flex-shrink-0 overflow-hidden">
            {bidLevels.map(level => (
              <BookRow
                key={`bid-${level.price}`}
                level={level}
                maxCum={maxBidCum}
                side="bid"
                prevSize={getPrevBidSize(level.price)}
              />
            ))}
          </div>

          {/* Depth imbalance bar */}
          <div className="flex-1" />
          <div className="flex-shrink-0 p-2 border-t border-border-subtle">
            <div className="text-2xs font-mono text-text-muted mb-1 flex justify-between">
              <span className="text-positive">BID {fmtSz(maxBidCum)}</span>
              <span>DEPTH IMBALANCE</span>
              <span className="text-negative">ASK {fmtSz(maxAskCum)}</span>
            </div>
            <div className="h-1.5 bg-bg-root rounded-full overflow-hidden flex">
              <div
                className="h-full bg-positive rounded-l-full transition-all duration-500"
                style={{ width: `${(maxBidCum / (maxBidCum + maxAskCum)) * 100}%` }}
              />
              <div
                className="h-full bg-negative rounded-r-full transition-all duration-500"
                style={{ flex: 1 }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default OrderBookL2

/**
 * CandlestickChart — Bloomberg-style OHLCV chart using lightweight-charts v5.
 * Includes volume histogram, crosshair tooltip, timeframe selector.
 */

import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickSeriesOptions,
  type HistogramSeriesOptions,
  type CandlestickData,
  type HistogramData,
  type Time,
  type MouseEventParams,
} from 'lightweight-charts'
import clsx from 'clsx'

export interface CandlestickChartProps {
  /** Ticker symbol displayed in the header */
  symbol: string
  /** OHLCV array — unix seconds for `time` field */
  data?: Array<{
    time: number
    open: number
    high: number
    low: number
    close: number
    volume?: number
  }>
  loading?: boolean
  onTimeframeChange?: (tf: string) => void
  timeframe?: string
}

// ── Timeframes ──────────────────────────────────────────────────────────────
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1D', '1W'] as const

// ── Chart colors ─────────────────────────────────────────────────────────────
const CHART_BG = '#000000'
const UP_COLOR = '#00e676'
const DOWN_COLOR = '#ff1744'
const GRID_COLOR = '#1a1a1a'
const CROSSHAIR_COLOR = '#ff6600'
const TEXT_COLOR = '#888888'
const WICK_UP = '#00e676'
const WICK_DOWN = '#ff1744'

export function CandlestickChart({
  symbol,
  data,
  loading = false,
  onTimeframeChange,
  timeframe = '1h',
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const [activeTimeframe, setActiveTimeframe] = useState(timeframe)

  // Tooltip state
  const [tooltip, setTooltip] = useState<{
    open: number; high: number; low: number; close: number; volume: number; change: number; changePct: number
  } | null>(null)
  const [currentPrice, setCurrentPrice] = useState<number | null>(null)
  const [currentChangePct, setCurrentChangePct] = useState<number | null>(null)

  const candles = useMemo(() => data ?? [], [data])

  // Derive last price / change from candle data
  useEffect(() => {
    if (candles.length >= 2) {
      const last = candles[candles.length - 1]
      const prev = candles[candles.length - 2]
      setCurrentPrice(last.close)
      setCurrentChangePct(((last.close - prev.close) / prev.close) * 100)
    }
  }, [candles])

  // Build / rebuild chart when container mounts
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: CHART_BG },
        textColor: TEXT_COLOR,
        fontFamily: '"IBM Plex Mono", monospace',
        fontSize: 10,
      },
      grid: {
        vertLines: { color: GRID_COLOR },
        horzLines: { color: GRID_COLOR },
      },
      crosshair: {
        vertLine: { color: CROSSHAIR_COLOR, width: 1, style: 3, labelBackgroundColor: '#ff6600' },
        horzLine: { color: CROSSHAIR_COLOR, width: 1, style: 3, labelBackgroundColor: '#ff6600' },
      },
      rightPriceScale: {
        borderColor: '#1e1e1e',
        textColor: TEXT_COLOR,
      },
      timeScale: {
        borderColor: '#1e1e1e',
        textColor: TEXT_COLOR,
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: true,
      handleScale: true,
    })

    // Candlestick series (main pane)
    const candleOptions: Partial<CandlestickSeriesOptions> = {
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: WICK_UP,
      wickDownColor: WICK_DOWN,
    }
    const candleSeries = chart.addSeries(CandlestickSeries, candleOptions)

    // Volume histogram (overlay on same pane, scaled small)
    const volumeOptions: Partial<HistogramSeriesOptions> = {
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    }
    const volumeSeries = chart.addSeries(HistogramSeries, volumeOptions)
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
      borderVisible: false,
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries

    // Crosshair move handler for tooltip
    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      if (!param.time || !param.seriesData) {
        setTooltip(null)
        return
      }
      const bar = param.seriesData.get(candleSeries) as CandlestickData<Time> | undefined
      if (!bar) { setTooltip(null); return }
      const volBar = param.seriesData.get(volumeSeries) as HistogramData<Time> | undefined
      const vol = volBar ? (volBar.value ?? 0) : 0
      const change = bar.close - bar.open
      const changePct = (change / bar.open) * 100
      setTooltip({
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        volume: vol,
        change,
        changePct,
      })
    })

    // Resize observer
    const ro = new ResizeObserver(entries => {
      const entry = entries[0]
      if (!entry) return
      const { width, height } = entry.contentRect
      chart.applyOptions({ width, height })
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      volumeSeriesRef.current = null
    }
  }, [])

  // Feed candle + volume data to series
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return

    const sorted = [...candles].sort((a, b) => a.time - b.time)
    const candleData: CandlestickData<Time>[] = sorted.map(c => ({
      time: c.time as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
    const volumeData: HistogramData<Time>[] = sorted.map(c => ({
      time: c.time as Time,
      value: c.volume ?? 0,
      color: c.close >= c.open ? 'rgba(0,230,118,0.35)' : 'rgba(255,23,68,0.35)',
    }))

    candleSeriesRef.current.setData(candleData)
    volumeSeriesRef.current.setData(volumeData)
    chartRef.current?.timeScale().fitContent()
  }, [candles])

  const handleTimeframeClick = useCallback((tf: string) => {
    setActiveTimeframe(tf)
    onTimeframeChange?.(tf)
  }, [onTimeframeChange])

  const formatPrice = (v: number) => v.toFixed(2)
  const formatVolume = (v: number) => {
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`
    if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`
    return String(v)
  }

  const lastCandle = candles[candles.length - 1]

  return (
    <div className="flex flex-col h-full w-full bg-bg-root overflow-hidden">
      {/* Panel header */}
      <div className="panel-header flex-shrink-0">
        <span className="text-accent-cyan">◈ Chart</span>
        <span className="text-text-secondary ml-2">{symbol}</span>
        {currentPrice !== null && (
          <>
            <span className="ml-3 text-text-primary tabular-nums">{formatPrice(currentPrice)}</span>
            {currentChangePct !== null && (
              <span
                className={clsx(
                  'ml-1 tabular-nums',
                  currentChangePct >= 0 ? 'text-positive' : 'text-negative',
                )}
              >
                {currentChangePct >= 0 ? '+' : ''}{currentChangePct.toFixed(2)}%
              </span>
            )}
          </>
        )}
        {/* Crosshair OHLCV tooltip in header */}
        {tooltip && (
          <span className="ml-4 flex gap-3 text-2xs tabular-nums">
            <span>O:<span className="text-text-primary ml-1">{formatPrice(tooltip.open)}</span></span>
            <span>H:<span className="text-positive ml-1">{formatPrice(tooltip.high)}</span></span>
            <span>L:<span className="text-negative ml-1">{formatPrice(tooltip.low)}</span></span>
            <span>C:<span className={clsx('ml-1', tooltip.change >= 0 ? 'text-positive' : 'text-negative')}>{formatPrice(tooltip.close)}</span></span>
            <span>V:<span className="text-text-secondary ml-1">{formatVolume(tooltip.volume)}</span></span>
            <span className={clsx('ml-1', tooltip.changePct >= 0 ? 'text-positive' : 'text-negative')}>
              {tooltip.changePct >= 0 ? '+' : ''}{tooltip.changePct.toFixed(2)}%
            </span>
          </span>
        )}
        <div className="ml-auto flex gap-1">
          {TIMEFRAMES.map(tf => (
            <button
              key={tf}
              onClick={() => handleTimeframeClick(tf)}
              className={clsx(
                'px-2 py-0.5 text-2xs font-mono rounded-sm border transition-colors',
                activeTimeframe === tf
                  ? 'bg-accent-cyan text-bg-root border-accent-cyan'
                  : 'bg-transparent text-text-secondary border-border-subtle hover:border-accent-cyan hover:text-accent-cyan',
              )}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Chart area */}
      <div className="relative flex-1 min-h-0">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-bg-root/80 z-10">
            <span className="text-accent-cyan text-xs font-mono animate-pulse">LOADING…</span>
          </div>
        )}

        {!loading && (!data || data.length === 0) && false /* always show chart with mock */ && (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-text-muted text-xs font-mono">NO DATA — {symbol}</span>
          </div>
        )}

        <div ref={containerRef} className="w-full h-full" />
      </div>

      {/* Bottom status bar */}
      <div className="flex-shrink-0 flex items-center gap-4 px-3 py-1 border-t border-border-subtle text-2xs font-mono text-text-muted tabular-nums">
        {lastCandle && (
          <>
            <span>O <span className="text-text-secondary">{formatPrice(lastCandle.open)}</span></span>
            <span>H <span className="text-positive">{formatPrice(lastCandle.high)}</span></span>
            <span>L <span className="text-negative">{formatPrice(lastCandle.low)}</span></span>
            <span>C <span className="text-text-primary">{formatPrice(lastCandle.close)}</span></span>
            {lastCandle.volume && <span>VOL <span className="text-text-secondary">{formatVolume(lastCandle.volume)}</span></span>}
          </>
        )}
        <span className="ml-auto">{activeTimeframe}</span>
      </div>
    </div>
  )
}

export default CandlestickChart

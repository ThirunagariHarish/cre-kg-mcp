import React, { useState, useRef, useEffect } from 'react'
import clsx from 'clsx'
import { Download } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface BacktestParams {
  strategy: string
  startDate: string
  endDate: string
  startingCapital: number
  commissionPerTrade: number
}

interface BacktestStats {
  totalReturn: number
  totalReturnPct: number
  sharpe: number
  maxDrawdown: number
  maxDrawdownPct: number
  winRate: number
  totalTrades: number
  profitFactor: number
}

interface BacktestTrade {
  id: string
  date: string
  ticker: string
  side: 'BUY' | 'SELL'
  entry: number
  exit: number
  pnl: number
  qty: number
}

interface BacktestResult {
  stats: BacktestStats
  equityCurve: { timestamp: number; equity: number }[]
  trades: BacktestTrade[]
}

// ── Agent list ────────────────────────────────────────────────────────────────

const AGENTS = [
  'MomentumAgent',
  'MeanReversionAgent',
  'TrendFollowAgent',
  'VolatilityAgent',
  'MacroAlpha',
]

// ── Mini equity curve SVG ─────────────────────────────────────────────────────

function EquityCurveChart({ data, startingCapital }: { data: { timestamp: number; equity: number }[]; startingCapital: number }) {
  if (data.length < 2) return null
  const W = 300
  const H = 80
  const PAD = { top: 6, right: 6, bottom: 6, left: 40 }
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom

  const values = data.map(p => p.equity)
  const minV = Math.min(...values)
  const maxV = Math.max(...values)
  const range = Math.max(maxV - minV, 1)

  function tx(i: number) {
    return PAD.left + (i / (data.length - 1)) * innerW
  }
  function ty(v: number) {
    return PAD.top + (1 - (v - minV) / range) * innerH
  }

  const points = data.map((p, i) => `${tx(i).toFixed(1)},${ty(p.equity).toFixed(1)}`).join(' ')
  const lastEquity = values[values.length - 1]
  const isProfit = lastEquity >= startingCapital
  const lineColor = isProfit ? '#00e676' : '#ff1744'

  const zeroY = ty(startingCapital)
  const clampedZeroY = Math.max(PAD.top, Math.min(PAD.top + innerH, zeroY))

  return (
    <svg width={W} height={H} className="block w-full">
      {/* Zero line */}
      <line
        x1={PAD.left} y1={clampedZeroY} x2={PAD.left + innerW} y2={clampedZeroY}
        stroke="#1e1e1e" strokeWidth="1"
      />
      {/* Equity line */}
      <polyline points={points} fill="none" stroke={lineColor} strokeWidth="1.5" />
      {/* Y labels */}
      <text x={PAD.left - 3} y={PAD.top + 4} fill="#444" fontSize="7" fontFamily="monospace" textAnchor="end">
        {(maxV / 1000).toFixed(0)}k
      </text>
      <text x={PAD.left - 3} y={PAD.top + innerH} fill="#444" fontSize="7" fontFamily="monospace" textAnchor="end">
        {(minV / 1000).toFixed(0)}k
      </text>
    </svg>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="p-2 bg-bg-root border border-border-subtle rounded-sm text-center">
      <div className="font-mono text-[0.5rem] text-text-muted uppercase tracking-widest mb-0.5">{label}</div>
      <div className={clsx('font-mono text-sm font-bold tabular-nums', color ?? 'text-text-primary')}>
        {value}
      </div>
    </div>
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function useProgress(running: boolean) {
  const [progress, setProgress] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (running) {
      setProgress(0)
      intervalRef.current = setInterval(() => {
        setProgress(p => {
          if (p >= 90) {
            if (intervalRef.current) clearInterval(intervalRef.current)
            return 90
          }
          return p + Math.random() * 12
        })
      }, 200)
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current)
      if (progress > 0) setProgress(100)
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [running]) // eslint-disable-line react-hooks/exhaustive-deps

  return progress
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function BacktestPanel() {
  const [params, setParams] = useState<BacktestParams>({
    strategy: AGENTS[0],
    startDate: '2024-01-01',
    endDate: '2024-12-31',
    startingCapital: 100000,
    commissionPerTrade: 1,
  })
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const progress = useProgress(running)

  async function handleRun() {
    setRunning(true)
    setResult(null)
    await new Promise(r => setTimeout(r, 500))
    setRunning(false)
    // Backtest engine not yet implemented — connect to historical data API
  }

  function handleExport() {
    if (!result) return
    const csv = [
      'Date,Ticker,Side,Entry,Exit,Qty,PnL',
      ...result.trades.map(t =>
        [t.date, t.ticker, t.side, t.entry, t.exit, t.qty, t.pnl].join(','),
      ),
    ].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `backtest_${params.strategy}_${params.startDate}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const stats = result?.stats

  return (
    <div className="flex flex-col h-full">
      <div className="panel-header">
        <span className="flex-1">◈ Backtest</span>
      </div>

      <div className="px-2.5 pt-2 space-y-2 overflow-y-auto flex-1">
        {/* Strategy */}
        <div>
          <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">Strategy</label>
          <select
            value={params.strategy}
            onChange={e => setParams(p => ({ ...p, strategy: e.target.value }))}
            className="terminal-input h-7 text-xs"
          >
            {AGENTS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>

        {/* Date range */}
        <div className="grid grid-cols-2 gap-1.5">
          <div>
            <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">Start Date</label>
            <input
              type="date"
              value={params.startDate}
              onChange={e => setParams(p => ({ ...p, startDate: e.target.value }))}
              className="terminal-input h-7 text-xs"
            />
          </div>
          <div>
            <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">End Date</label>
            <input
              type="date"
              value={params.endDate}
              onChange={e => setParams(p => ({ ...p, endDate: e.target.value }))}
              className="terminal-input h-7 text-xs"
            />
          </div>
        </div>

        {/* Capital & commission */}
        <div className="grid grid-cols-2 gap-1.5">
          <div>
            <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">Starting Capital ($)</label>
            <input
              type="number"
              min="1000"
              step="1000"
              value={params.startingCapital}
              onChange={e => setParams(p => ({ ...p, startingCapital: Number(e.target.value) }))}
              className="terminal-input h-7 tabular-nums"
            />
          </div>
          <div>
            <label className="block font-mono text-[0.55rem] text-text-muted uppercase tracking-widest mb-0.5">Commission / Trade ($)</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={params.commissionPerTrade}
              onChange={e => setParams(p => ({ ...p, commissionPerTrade: Number(e.target.value) }))}
              className="terminal-input h-7 tabular-nums"
            />
          </div>
        </div>

        {/* Run button */}
        <button
          type="button"
          onClick={handleRun}
          disabled={running}
          className={clsx(
            'w-full py-2 font-mono text-[0.72rem] font-bold uppercase tracking-wider rounded-sm border transition-colors',
            running
              ? 'bg-bg-panel border-border-subtle text-text-muted cursor-not-allowed'
              : 'bg-accent-cyan border-accent-cyan text-bg-root hover:bg-accent-cyan-dim',
          )}
        >
          {running ? 'Running Backtest...' : '▶ Run Backtest'}
        </button>

        {/* Progress bar */}
        {running && (
          <div>
            <div className="flex justify-between mb-0.5">
              <span className="font-mono text-[0.55rem] text-text-muted">Progress</span>
              <span className="font-mono text-[0.55rem] text-accent-cyan tabular-nums">{Math.round(progress)}%</span>
            </div>
            <div className="h-1.5 bg-bg-panel-raised rounded-full overflow-hidden">
              <div
                className="h-full bg-accent-cyan rounded-full transition-all duration-200"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Results */}
        {result && stats && (
          <>
            {/* Equity curve */}
            <div className="border border-border-subtle rounded-sm overflow-hidden">
              <div className="px-2 pt-1.5 pb-0.5">
                <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">Equity Curve</span>
              </div>
              <div className="px-1 pb-1">
                <EquityCurveChart data={result.equityCurve} startingCapital={params.startingCapital} />
              </div>
            </div>

            {/* Key stats grid */}
            <div className="grid grid-cols-4 gap-1">
              <StatCard
                label="Total Return"
                value={`${stats.totalReturnPct >= 0 ? '+' : ''}${stats.totalReturnPct.toFixed(1)}%`}
                color={stats.totalReturnPct >= 0 ? 'text-positive' : 'text-negative'}
              />
              <StatCard
                label="Sharpe"
                value={stats.sharpe.toFixed(2)}
                color={stats.sharpe >= 1 ? 'text-positive' : stats.sharpe >= 0.5 ? 'text-warning' : 'text-negative'}
              />
              <StatCard
                label="Max DD"
                value={`-${stats.maxDrawdownPct.toFixed(1)}%`}
                color="text-negative"
              />
              <StatCard
                label="Win Rate"
                value={`${(stats.winRate * 100).toFixed(0)}%`}
                color={stats.winRate >= 0.55 ? 'text-positive' : stats.winRate >= 0.45 ? 'text-warning' : 'text-negative'}
              />
              <StatCard
                label="Trades"
                value={String(stats.totalTrades)}
              />
              <StatCard
                label="Profit Factor"
                value={stats.profitFactor.toFixed(2)}
                color={stats.profitFactor >= 1.5 ? 'text-positive' : stats.profitFactor >= 1 ? 'text-warning' : 'text-negative'}
              />
              <StatCard
                label="Max Drawdown"
                value={`-$${Math.round(stats.maxDrawdown).toLocaleString()}`}
                color="text-negative"
              />
              <StatCard
                label="Net P&L"
                value={`${stats.totalReturn >= 0 ? '+' : ''}$${Math.round(stats.totalReturn).toLocaleString()}`}
                color={stats.totalReturn >= 0 ? 'text-positive' : 'text-negative'}
              />
            </div>

            {/* Trades table */}
            <div>
              <span className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest">Trades</span>
              <div className="mt-1 border border-border-subtle rounded-sm overflow-hidden">
                <div className="overflow-auto max-h-48">
                  <table className="w-full border-collapse">
                    <thead className="sticky top-0 bg-bg-panel">
                      <tr>
                        {['Date', 'Ticker', 'Side', 'Entry', 'Exit', 'P&L'].map(h => (
                          <th key={h} className="py-1 px-1.5 font-mono text-[0.5rem] uppercase tracking-wider text-text-muted text-right first:text-left border-b border-border-subtle">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.map(trade => (
                        <tr key={trade.id} className="border-b border-border-muted hover:bg-bg-panel-hover">
                          <td className="py-0.5 px-1.5 font-mono text-[0.6rem] text-text-muted">{trade.date}</td>
                          <td className="py-0.5 px-1.5 font-mono text-[0.6rem] text-accent-cyan font-semibold text-right">{trade.ticker}</td>
                          <td className={clsx('py-0.5 px-1.5 font-mono text-[0.6rem] font-semibold text-right', trade.side === 'BUY' ? 'text-positive' : 'text-negative')}>
                            {trade.side}
                          </td>
                          <td className="py-0.5 px-1.5 font-mono text-[0.6rem] text-text-primary tabular-nums text-right">${trade.entry.toFixed(2)}</td>
                          <td className="py-0.5 px-1.5 font-mono text-[0.6rem] text-text-primary tabular-nums text-right">${trade.exit.toFixed(2)}</td>
                          <td className={clsx('py-0.5 px-1.5 font-mono text-[0.6rem] font-semibold tabular-nums text-right', trade.pnl >= 0 ? 'text-positive' : 'text-negative')}>
                            {trade.pnl >= 0 ? '+' : ''}{trade.pnl.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* Export */}
            <button
              type="button"
              onClick={handleExport}
              className="flex items-center justify-center gap-1.5 w-full py-1.5 font-mono text-[0.62rem] border border-border-subtle text-text-muted rounded-sm hover:border-accent-cyan hover:text-text-secondary transition-colors"
            >
              <Download size={10} />
              Export Results (CSV)
            </button>
          </>
        )}
      </div>
    </div>
  )
}

import React, { useState, useMemo } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ─────────────────────────────────────────────────────────────────────

interface TradeRecord {
  symbol: string
  side: 'LONG' | 'SHORT'
  entry: number
  exit: number | null
  shares: number
  pnl: number
  status: 'CLOSED' | 'OPEN'
  time: string
}

interface AgentFire {
  agent: string
  category: string
  signals: number
  pnl: number
}

export interface JournalEntry {
  date: string
  marketSummary: string
  trades: TradeRecord[]
  agentFires: AgentFire[]
  notes: string
  watchlist: string[]
}

export interface TradeJournalPanelProps {
  date?: Date
  entry?: JournalEntry
  loading?: boolean
}


const WEEKEND_DAYS = [0, 6] // Sunday, Saturday

// ── Utils ─────────────────────────────────────────────────────────────────────

function addDays(d: Date, n: number): Date {
  const result = new Date(d)
  result.setDate(result.getDate() + n)
  return result
}

function skipWeekends(d: Date, direction: number): Date {
  let result = addDays(d, direction)
  while (WEEKEND_DAYS.includes(result.getDay())) {
    result = addDays(result, direction)
  }
  return result
}

function formatDateDisplay(d: Date): string {
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}

function isToday(d: Date): boolean {
  const now = new Date()
  return d.toDateString() === now.toDateString()
}

// ── Section Header ────────────────────────────────────────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-border-subtle">
      <span className="text-[0.58rem] font-mono tracking-widest text-accent-cyan uppercase">{label}</span>
      <div className="flex-1 border-t border-border-subtle" />
    </div>
  )
}

// ── Trade Table ───────────────────────────────────────────────────────────────

function TradeTable({ trades }: { trades: TradeRecord[] }) {
  return (
    <table className="data-table w-full">
      <thead>
        <tr>
          <th className="!text-left">Symbol</th>
          <th>Side</th>
          <th>Time</th>
          <th>Entry</th>
          <th>Exit</th>
          <th>Shares</th>
          <th>P&L</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t, i) => (
          <tr key={i}>
            <td className="!text-left text-accent-cyan font-semibold">{t.symbol}</td>
            <td className={t.side === 'LONG' ? 'text-positive' : 'text-negative'}>{t.side}</td>
            <td className="text-text-secondary">{t.time}</td>
            <td className="tabular-nums">${t.entry.toFixed(2)}</td>
            <td className="tabular-nums">{t.exit != null ? `$${t.exit.toFixed(2)}` : '—'}</td>
            <td className="tabular-nums">{t.shares}</td>
            <td className={clsx('tabular-nums font-semibold', t.pnl >= 0 ? 'text-positive' : 'text-negative')}>
              {t.pnl >= 0 ? '+' : ''}${Math.abs(t.pnl).toFixed(0)}
            </td>
            <td>
              <span
                className={clsx(
                  'px-1 py-0 text-[0.5rem] border font-mono tracking-widest',
                  t.status === 'OPEN'
                    ? 'text-warning border-warning/40'
                    : 'text-text-muted border-border-subtle',
                )}
              >
                {t.status}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ── Export Helper ─────────────────────────────────────────────────────────────

function exportJournalEntry(entry: JournalEntry, dateLabel: string): void {
  const lines = [
    `TRADING JOURNAL — ${dateLabel}`,
    '='.repeat(60),
    '',
    'MARKET SUMMARY',
    '-'.repeat(40),
    entry.marketSummary,
    '',
    'TRADES',
    '-'.repeat(40),
    ['Symbol', 'Side', 'Time', 'Entry', 'Exit', 'Shares', 'P&L', 'Status'].join('\t'),
    ...entry.trades.map((t) =>
      [t.symbol, t.side, t.time, t.entry, t.exit ?? '-', t.shares, t.pnl, t.status].join('\t'),
    ),
    '',
    'AGENT PERFORMANCE',
    '-'.repeat(40),
    ...entry.agentFires.map((a) => `${a.agent} (${a.category}): ${a.signals} signals, $${a.pnl} P&L`),
    '',
    'NOTES',
    '-'.repeat(40),
    entry.notes,
    '',
    "TOMORROW'S WATCHLIST",
    '-'.repeat(40),
    entry.watchlist.join(', '),
  ]

  const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `journal-${new Date().toISOString().slice(0, 10)}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function TradeJournalPanel({
  date: dateProp,
  entry: entryProp,
  loading = false,
}: TradeJournalPanelProps) {
  const [currentDate, setCurrentDate] = useState<Date>(
    dateProp ?? new Date(),
  )
  const [notes, setNotes] = useState<string | null>(null)

  const { data: orders = [] } = useQuery({
    queryKey: ['orders-journal'],
    queryFn: () => apiGet<any[]>(API.orders),
    refetchInterval: 60_000,
    placeholderData: [],
  })

  const isWeekend = WEEKEND_DAYS.includes(currentDate.getDay())

  const currentDateStr = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, '0')}-${String(currentDate.getDate()).padStart(2, '0')}`

  const liveEntry: JournalEntry | null = useMemo(() => {
    if (isWeekend || orders.length === 0) return null
    const todaysOrders = orders.filter((o: any) => {
      const filledAt = o.filled_at ?? o.created_at ?? ''
      return filledAt.startsWith(currentDateStr)
    })
    if (todaysOrders.length === 0) return null
    const trades: TradeRecord[] = todaysOrders.map((o: any) => ({
      symbol: o.symbol ?? '',
      side: (o.side ?? 'LONG').toUpperCase() === 'BUY' ? 'LONG' : 'SHORT',
      entry: o.avg_fill_price ?? o.limit_price ?? 0,
      exit: o.status === 'FILLED' ? (o.avg_fill_price ?? null) : null,
      shares: o.quantity ?? o.qty ?? 0,
      pnl: o.realized_pnl ?? 0,
      status: o.status === 'FILLED' ? 'CLOSED' : 'OPEN',
      time: o.filled_at ? new Date(o.filled_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false }) : '--:--',
    }))
    return {
      date: formatDateDisplay(currentDate),
      marketSummary: '',
      trades,
      agentFires: [],
      notes: '',
      watchlist: [],
    }
  }, [orders, currentDateStr, isWeekend, currentDate])

  const entry = entryProp ?? liveEntry

  const effectiveNotes = notes ?? entry?.notes ?? ''

  function goToPrev() {
    setCurrentDate((d) => skipWeekends(d, -1))
    setNotes(null)
  }
  function goToNext() {
    const next = skipWeekends(currentDate, 1)
    if (next <= new Date()) {
      setCurrentDate(next)
      setNotes(null)
    }
  }

  const todayPnl = entry?.trades.reduce((s, t) => s + t.pnl, 0) ?? 0
  const dateLabel = formatDateDisplay(currentDate)
  const isTodayDate = isToday(currentDate)

  if (loading) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ TRADE JOURNAL</div>
        <div className="flex-1 skeleton m-2 rounded-sm" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
      {/* Header */}
      <div className="panel-header flex-shrink-0">
        <span>◈ TRADE JOURNAL</span>
        {entry && (
          <span
            className={clsx(
              'ml-2 text-[0.6rem] font-mono tabular-nums',
              todayPnl >= 0 ? 'text-positive' : 'text-negative',
            )}
          >
            {todayPnl >= 0 ? '+' : ''}
            {todayPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {/* Date Navigator */}
          <button
            onClick={goToPrev}
            className="w-5 h-5 flex items-center justify-center text-text-secondary hover:text-accent-cyan border border-border-subtle hover:border-accent-cyan/40 transition-colors text-[0.7rem]"
            aria-label="Previous trading day"
          >
            ‹
          </button>
          <span
            className={clsx(
              'text-[0.6rem] font-mono tracking-wide',
              isTodayDate ? 'text-accent-cyan' : 'text-text-secondary',
            )}
          >
            {formatDateDisplay(currentDate)}
          </span>
          <button
            onClick={goToNext}
            className="w-5 h-5 flex items-center justify-center text-text-secondary hover:text-accent-cyan border border-border-subtle hover:border-accent-cyan/40 transition-colors text-[0.7rem]"
            aria-label="Next trading day"
          >
            ›
          </button>
          {entry && (
            <button
              onClick={() => exportJournalEntry({ ...entry, notes: effectiveNotes }, dateLabel)}
              className="px-1.5 py-0.5 text-[0.55rem] font-mono border border-border-subtle text-text-muted hover:text-text-secondary hover:border-accent-cyan/40 transition-colors"
            >
              EXPORT
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto min-h-0 p-2 space-y-3">
        {!entry ? (
          <div className="flex flex-col items-center justify-center h-32 text-text-muted font-mono text-[0.7rem]">
            <span className="text-2xl mb-2 opacity-20">⊘</span>
            <span>No journal entry for {dateLabel}</span>
          </div>
        ) : (
          <>
            {/* Market Summary */}
            <div>
              <SectionHeader label="Market Summary" />
              <p className="text-[0.65rem] font-mono text-text-secondary leading-relaxed pt-1.5">
                {entry.marketSummary}
              </p>
            </div>

            {/* Trades */}
            <div>
              <SectionHeader label={`Today's Trades (${entry.trades.length})`} />
              <div className="overflow-x-auto pt-1">
                <TradeTable trades={entry.trades} />
              </div>
            </div>

            {/* Agent Performance */}
            <div>
              <SectionHeader label="Agent Performance" />
              <div className="pt-1 space-y-0.5">
                {entry.agentFires.map((a) => (
                  <div
                    key={a.agent}
                    className="flex items-center gap-2 py-0.5 px-1 hover:bg-bg-panel-raised transition-colors"
                  >
                    <span className="text-[0.6rem] font-mono text-text-primary w-28 truncate">{a.agent}</span>
                    <span className="px-1 text-[0.5rem] border border-border-subtle text-text-muted font-mono tracking-widest">
                      {a.category}
                    </span>
                    <span className="text-[0.6rem] font-mono text-text-muted ml-2">{a.signals} sig</span>
                    <span
                      className={clsx(
                        'ml-auto text-[0.62rem] font-mono tabular-nums',
                        a.pnl >= 0 ? 'text-positive' : 'text-negative',
                      )}
                    >
                      {a.pnl >= 0 ? '+' : ''}${Math.abs(a.pnl).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Notes */}
            <div>
              <SectionHeader label="Notes" />
              <textarea
                className="w-full mt-1 bg-bg-panel-raised border border-border-subtle text-[0.65rem] font-mono text-text-primary leading-relaxed p-2 resize-none outline-none focus:border-accent-cyan/60 transition-colors"
                rows={4}
                value={effectiveNotes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Add your trading notes here..."
                aria-label="Journal notes"
              />
            </div>

            {/* Watchlist */}
            <div>
              <SectionHeader label="Tomorrow's Watchlist" />
              <div className="flex flex-wrap gap-1.5 pt-1.5">
                {entry.watchlist.map((sym) => (
                  <span
                    key={sym}
                    className="px-2 py-0.5 text-[0.6rem] font-mono text-accent-cyan border border-accent-cyan/30 bg-accent-cyan/5"
                  >
                    {sym}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

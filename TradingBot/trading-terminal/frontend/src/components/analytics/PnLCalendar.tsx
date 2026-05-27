import React, { useMemo, useState } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CalendarDay {
  date: string    // 'YYYY-MM-DD'
  pnl: number
  trades: number
}

export interface PnLCalendarProps {
  month?: number   // 0-indexed (0 = Jan)
  year?: number
  data?: CalendarDay[]
  loading?: boolean
}


// ── Color Helpers ─────────────────────────────────────────────────────────────

function pnlToColor(pnl: number, maxAbsPnl: number): string {
  if (pnl === 0 || maxAbsPnl === 0) return '#1a1a1a'
  const intensity = Math.min(Math.abs(pnl) / maxAbsPnl, 1)
  if (pnl > 0) {
    const g = Math.round(50 + intensity * 180)
    const r = Math.round(0)
    const b = Math.round(intensity * 40)
    return `rgba(${r}, ${g}, ${b}, ${0.3 + intensity * 0.55})`
  } else {
    const r = Math.round(80 + intensity * 175)
    const g = Math.round(0)
    const b = Math.round(intensity * 40)
    return `rgba(${r}, ${g}, ${b}, ${0.3 + intensity * 0.55})`
  }
}

// ── Month Navigation ──────────────────────────────────────────────────────────

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const DAY_LABELS = ['MON', 'TUE', 'WED', 'THU', 'FRI']

// ── Tooltip ───────────────────────────────────────────────────────────────────

interface DayTooltipProps {
  day: CalendarDay
  visible: boolean
}

function DayTooltip({ day, visible }: DayTooltipProps) {
  if (!visible) return null
  const date = new Date(day.date + 'T12:00:00')
  const label = date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  return (
    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 z-50 bg-bg-panel border border-border-subtle px-2 py-1 font-mono text-[0.58rem] whitespace-nowrap shadow-panel pointer-events-none">
      <div className="text-text-muted">{label}</div>
      <div className={clsx(day.pnl >= 0 ? 'text-positive' : 'text-negative', 'font-semibold')}>
        {day.pnl >= 0 ? '+' : ''}${Math.abs(day.pnl).toLocaleString('en-US', { minimumFractionDigits: 0 })}
      </div>
      <div className="text-text-muted">{day.trades} trade{day.trades !== 1 ? 's' : ''}</div>
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function PnLCalendar({
  month: monthProp,
  year: yearProp,
  data,
  loading = false,
}: PnLCalendarProps) {
  const today = new Date()
  const [currentYear, setCurrentYear] = useState(yearProp ?? today.getFullYear())
  const [currentMonth, setCurrentMonth] = useState(monthProp ?? today.getMonth())
  const [hoveredDate, setHoveredDate] = useState<string | null>(null)

  const { data: equityCurve = [] } = useQuery({
    queryKey: ['equity-curve-calendar', `${currentYear}-${currentMonth}`],
    queryFn: () => apiGet<any[]>(API.equityCurve('1mo')),
    refetchInterval: 60_000,
    placeholderData: [],
  })

  const derivedCalendarData = useMemo((): CalendarDay[] => {
    const pnlByDate: Record<string, number> = {}
    let prevValue: number | null = null
    equityCurve.forEach((p: any) => {
      const val = p.value ?? p.equity ?? 0
      const dateStr = (p.date ?? '').substring(0, 10)
      if (prevValue !== null && dateStr) {
        pnlByDate[dateStr] = val - prevValue
      }
      prevValue = val
    })
    return Object.entries(pnlByDate).map(([date, pnl]) => ({
      date,
      pnl: Math.round(pnl * 100) / 100,
      trades: 0,
    }))
  }, [equityCurve])

  const calendarData = useMemo(
    () => data ?? derivedCalendarData,
    [data, derivedCalendarData],
  )

  const dataMap = useMemo(() => {
    const m = new Map<string, CalendarDay>()
    for (const d of calendarData) m.set(d.date, d)
    return m
  }, [calendarData])

  const maxAbsPnl = useMemo(
    () => Math.max(...calendarData.map((d) => Math.abs(d.pnl)), 1),
    [calendarData],
  )

  const monthlyTotal = useMemo(
    () => calendarData.reduce((s, d) => s + d.pnl, 0),
    [calendarData],
  )

  function prevMonth() {
    if (currentMonth === 0) { setCurrentMonth(11); setCurrentYear((y) => y - 1) }
    else setCurrentMonth((m) => m - 1)
  }
  function nextMonth() {
    const next = new Date(currentYear, currentMonth + 1, 1)
    if (next <= new Date()) {
      if (currentMonth === 11) { setCurrentMonth(0); setCurrentYear((y) => y + 1) }
      else setCurrentMonth((m) => m + 1)
    }
  }

  // Build weeks: each week is Mon-Fri
  const weeks = useMemo(() => {
    const firstDay = new Date(currentYear, currentMonth, 1)
    const lastDay = new Date(currentYear, currentMonth + 1, 0)
    const weeksArr: Array<Array<Date | null>> = []
    let week: Array<Date | null> = []

    // Pad to Monday
    const firstDow = firstDay.getDay() === 0 ? 6 : firstDay.getDay() - 1 // Mon=0
    for (let i = 0; i < firstDow && i < 5; i++) week.push(null)

    for (let d = 1; d <= lastDay.getDate(); d++) {
      const date = new Date(currentYear, currentMonth, d)
      const dow = date.getDay()
      if (dow === 0 || dow === 6) continue
      week.push(date)
      if (week.length === 5) {
        weeksArr.push(week)
        week = []
      }
    }
    if (week.length > 0) {
      while (week.length < 5) week.push(null)
      weeksArr.push(week)
    }
    return weeksArr
  }, [currentYear, currentMonth])

  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`

  if (loading) {
    return (
      <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
        <div className="panel-header">◈ P&L CALENDAR</div>
        <div className="flex-1 skeleton m-2 rounded-sm" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-bg-panel border border-border-subtle">
      {/* Header */}
      <div className="panel-header flex-shrink-0">
        <span>◈ P&L CALENDAR</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={prevMonth}
            className="w-5 h-5 flex items-center justify-center text-text-secondary hover:text-accent-cyan border border-border-subtle hover:border-accent-cyan/40 transition-colors text-[0.7rem]"
            aria-label="Previous month"
          >
            ‹
          </button>
          <span className="text-[0.6rem] font-mono tracking-wide text-text-secondary">
            {MONTH_NAMES[currentMonth]} {currentYear}
          </span>
          <button
            onClick={nextMonth}
            className="w-5 h-5 flex items-center justify-center text-text-secondary hover:text-accent-cyan border border-border-subtle hover:border-accent-cyan/40 transition-colors text-[0.7rem]"
            aria-label="Next month"
          >
            ›
          </button>
        </div>
      </div>

      {/* Calendar */}
      <div className="flex-1 overflow-auto min-h-0 p-2">
        {/* Day labels */}
        <div className="grid grid-cols-5 gap-px mb-1">
          {DAY_LABELS.map((d) => (
            <div
              key={d}
              className="text-center text-[0.52rem] font-mono tracking-widest text-text-muted py-0.5"
            >
              {d}
            </div>
          ))}
        </div>

        {/* Weeks */}
        <div className="space-y-px">
          {weeks.map((week, wi) => (
            <div key={wi} className="grid grid-cols-5 gap-px">
              {week.map((date, di) => {
                if (!date) {
                  return <div key={di} className="h-12" />
                }
                const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
                const dayData = dataMap.get(dateStr)
                const isToday = dateStr === todayStr
                const isFuture = date > today
                const isHovered = hoveredDate === dateStr
                const bg = dayData && !isFuture ? pnlToColor(dayData.pnl, maxAbsPnl) : '#111111'

                return (
                  <div
                    key={di}
                    className={clsx(
                      'relative h-12 flex flex-col items-center justify-center cursor-default border transition-all',
                      isToday ? 'border-accent-cyan' : 'border-transparent',
                      !isFuture && dayData ? 'hover:border-border-subtle' : '',
                      isFuture && 'opacity-30',
                    )}
                    style={{ backgroundColor: bg }}
                    onMouseEnter={() => !isFuture && dayData && setHoveredDate(dateStr)}
                    onMouseLeave={() => setHoveredDate(null)}
                    role="gridcell"
                    aria-label={dayData ? `${dateStr}: $${dayData.pnl}` : dateStr}
                  >
                    <span
                      className={clsx(
                        'text-[0.55rem] font-mono tabular-nums',
                        isToday ? 'text-accent-cyan font-semibold' : 'text-text-muted',
                      )}
                    >
                      {date.getDate()}
                    </span>
                    {dayData && !isFuture && (
                      <span
                        className={clsx(
                          'text-[0.58rem] font-mono tabular-nums font-semibold',
                          dayData.pnl >= 0 ? 'text-positive' : 'text-negative',
                        )}
                      >
                        {dayData.pnl >= 0 ? '+' : ''}
                        {Math.abs(dayData.pnl) >= 1000
                          ? `$${(dayData.pnl / 1000).toFixed(1)}k`
                          : `$${Math.abs(dayData.pnl)}`}
                      </span>
                    )}
                    {dayData && isHovered && (
                      <DayTooltip day={dayData} visible={true} />
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        {/* Monthly Total */}
        <div className="mt-2 flex items-center justify-between px-1 py-1.5 border-t border-border-subtle">
          <span className="text-[0.58rem] font-mono tracking-widest text-text-muted uppercase">
            {MONTH_NAMES[currentMonth]} Total
          </span>
          <span
            className={clsx(
              'text-sm font-mono font-semibold tabular-nums',
              monthlyTotal >= 0 ? 'text-positive' : 'text-negative',
            )}
          >
            {monthlyTotal >= 0 ? '+' : ''}
            {monthlyTotal.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}
          </span>
        </div>

        {/* Color Legend */}
        <div className="flex items-center gap-2 px-1">
          <span className="text-[0.5rem] font-mono text-text-muted">LOSS</span>
          <div
            className="flex-1 h-1.5 rounded-sm"
            style={{
              background:
                'linear-gradient(to right, rgba(255,23,68,0.8), rgba(17,17,17,1), rgba(0,230,118,0.8))',
            }}
          />
          <span className="text-[0.5rem] font-mono text-text-muted">PROFIT</span>
        </div>
      </div>
    </div>
  )
}

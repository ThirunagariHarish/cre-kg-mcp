/**
 * OptionsChain — Bloomberg-style options chain viewer.
 * Two-sided table (calls / puts) with strike center column.
 */

import React, { useState, useMemo, useEffect } from 'react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Types ────────────────────────────────────────────────────────────────────

interface OptionLeg {
  bid: number
  ask: number
  last: number
  volume: number
  openInterest: number
  iv: number       // implied volatility 0-1
  delta: number
}

interface StrikeRow {
  strike: number
  call: OptionLeg
  put: OptionLeg
}

export interface OptionsChainData {
  underlyingPrice: number
  expiries: string[]
  strikes: Record<string, StrikeRow[]> // keyed by expiry string
}

export interface OptionsChainProps {
  symbol?: string
  loading?: boolean
  data?: OptionsChainData
}


// ── Helper formatters ─────────────────────────────────────────────────────────

const fmtP = (v: number) => v.toFixed(2)
const fmtIV = (v: number) => `${(v * 100).toFixed(1)}%`
const fmtDelta = (v: number) => v.toFixed(3)
const fmtNum = (v: number) => {
  if (v >= 1000) return `${(v / 1000).toFixed(1)}K`
  return String(v)
}

function ivColor(iv: number): string {
  if (iv < 0.3) return 'text-positive'
  if (iv < 0.5) return 'text-warning'
  return 'text-negative'
}

// ── Sub-components ───────────────────────────────────────────────────────────

interface LegCellsProps {
  leg: OptionLeg
  side: 'call' | 'put'
}

function LegCells({ leg, side }: LegCellsProps) {
  const orderCls = side === 'put' ? 'order-last' : ''
  return (
    <>
      <td className={clsx('tabular-nums text-text-primary', orderCls)}>{fmtP(leg.bid)}</td>
      <td className={clsx('tabular-nums text-text-primary', orderCls)}>{fmtP(leg.ask)}</td>
      <td className={clsx('tabular-nums text-text-secondary', orderCls)}>{fmtP(leg.last)}</td>
      <td className={clsx('tabular-nums text-text-secondary', orderCls)}>{fmtNum(leg.volume)}</td>
      <td className={clsx('tabular-nums text-text-secondary', orderCls)}>{fmtNum(leg.openInterest)}</td>
      <td className={clsx('tabular-nums', ivColor(leg.iv), orderCls)}>{fmtIV(leg.iv)}</td>
      <td className={clsx('tabular-nums text-text-secondary', orderCls)}>{fmtDelta(leg.delta)}</td>
    </>
  )
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr>
      {Array.from({ length: 15 }).map((_, i) => (
        <td key={i} className="p-1">
          <div className="skeleton h-3 rounded-sm w-full" />
        </td>
      ))}
    </tr>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function OptionsChain({ symbol, loading = false, data }: OptionsChainProps) {
  const resolvedSymbol = symbol ?? 'AAPL'
  const [selectedExpiry, setSelectedExpiry] = useState('')

  const { data: expiries = [] } = useQuery({
    queryKey: ['options-expiries', resolvedSymbol],
    queryFn: () => apiGet<string[]>(API.optionsExpiries(resolvedSymbol)),
    enabled: !!resolvedSymbol && !data,
    staleTime: 300_000,
  })

  useEffect(() => {
    if (expiries.length > 0 && !selectedExpiry) {
      setSelectedExpiry(expiries[0])
    }
  }, [expiries, selectedExpiry])

  const { data: rawChain, isLoading: chainLoading } = useQuery({
    queryKey: ['options-chain', resolvedSymbol, selectedExpiry],
    queryFn: () => apiGet<any>(`${API.optionsChain(resolvedSymbol)}?expiry=${selectedExpiry}`),
    enabled: !!resolvedSymbol && !!selectedExpiry && !data,
    staleTime: 60_000,
  })

  // Map raw API response to OptionsChainData shape
  const liveChainData: OptionsChainData | null = useMemo(() => {
    if (!rawChain) return null
    const calls = rawChain.calls ?? []
    const puts = rawChain.puts ?? []
    const strikesSet = new Set<number>([
      ...calls.map((c: any) => c.strike),
      ...puts.map((p: any) => p.strike),
    ])
    const strikeRows: StrikeRow[] = Array.from(strikesSet).sort((a, b) => a - b).map(strike => {
      const call = calls.find((c: any) => c.strike === strike)
      const put = puts.find((p: any) => p.strike === strike)
      const toleg = (leg: any): OptionLeg => ({
        bid: leg?.bid ?? 0,
        ask: leg?.ask ?? 0,
        last: leg?.last ?? ((leg?.bid ?? 0) + (leg?.ask ?? 0)) / 2,
        volume: leg?.volume ?? 0,
        openInterest: leg?.openInterest ?? 0,
        iv: leg?.impliedVolatility ?? 0,
        delta: leg?.delta ?? 0,
      })
      return { strike, call: toleg(call), put: toleg(put) }
    })
    return {
      underlyingPrice: rawChain.underlyingPrice ?? 0,
      expiries,
      strikes: { [selectedExpiry]: strikeRows },
    }
  }, [rawChain, expiries, selectedExpiry])

  const chainData: OptionsChainData = data ?? liveChainData ?? {
    underlyingPrice: 0,
    expiries: [],
    strikes: {},
  }

  const rows = useMemo(
    () => chainData.strikes[selectedExpiry] ?? [],
    [chainData.strikes, selectedExpiry],
  )

  const atmStrike = Math.round(chainData.underlyingPrice / 5) * 5
  const isLoading = loading || chainLoading

  const colHeader = (label: string) => (
    <th className="text-right text-text-muted px-1 py-1 text-2xs uppercase tracking-wider font-mono">{label}</th>
  )

  return (
    <div className="flex flex-col h-full w-full bg-bg-panel overflow-hidden">
      {/* Panel header */}
      <div className="panel-header flex-shrink-0">
        <span className="text-accent-cyan">◈ Options Chain</span>
        <span className="text-text-secondary ml-2">{resolvedSymbol}</span>
        <span className="text-text-muted ml-2">|</span>
        <span className="text-text-muted ml-2 text-2xs">UNDER: </span>
        <span className="text-text-primary ml-1 tabular-nums">{fmtP(chainData.underlyingPrice)}</span>

        {/* Expiry selector */}
        <div className="ml-auto flex gap-1">
          {chainData.expiries.map(exp => (
            <button
              key={exp}
              onClick={() => setSelectedExpiry(exp)}
              className={clsx(
                'px-2 py-0.5 text-2xs font-mono rounded-sm border transition-colors',
                selectedExpiry === exp
                  ? 'bg-accent-cyan text-bg-root border-accent-cyan'
                  : 'bg-transparent text-text-secondary border-border-subtle hover:border-accent-cyan hover:text-accent-cyan',
              )}
            >
              {exp}
            </button>
          ))}
        </div>
      </div>

      {/* Empty state */}
      {!isLoading && rows.length === 0 && (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-text-muted font-mono text-xs">SELECT SYMBOL</span>
        </div>
      )}

      {/* Table */}
      {(isLoading || rows.length > 0) && (
        <div className="flex-1 overflow-auto min-h-0">
          <table className="data-table w-full">
            <thead>
              <tr>
                {/* CALLS */}
                {colHeader('BID')}
                {colHeader('ASK')}
                {colHeader('LAST')}
                {colHeader('VOL')}
                {colHeader('OI')}
                {colHeader('IV%')}
                {colHeader('DELTA')}
                {/* STRIKE center */}
                <th className="text-center text-accent-cyan px-2 py-1 text-2xs uppercase tracking-wider font-mono bg-bg-panel-raised">
                  STRIKE
                </th>
                {/* PUTS */}
                {colHeader('BID')}
                {colHeader('ASK')}
                {colHeader('LAST')}
                {colHeader('VOL')}
                {colHeader('OI')}
                {colHeader('IV%')}
                {colHeader('DELTA')}
              </tr>
            </thead>
            <tbody>
              {isLoading
                ? Array.from({ length: 10 }).map((_, i) => <SkeletonRow key={i} />)
                : rows.map(row => {
                    const isAtm = Math.abs(row.strike - atmStrike) / atmStrike < 0.02
                    const callItm = row.strike < chainData.underlyingPrice
                    const putItm = row.strike > chainData.underlyingPrice
                    return (
                      <tr
                        key={row.strike}
                        className={clsx(
                          'border-b border-border-muted hover:bg-bg-panel-hover transition-colors',
                          isAtm && 'bg-[rgba(255,102,0,0.05)]',
                        )}
                      >
                        {/* Call cells */}
                        <td
                          className={clsx(
                            'tabular-nums text-text-primary px-1 text-right',
                            callItm && 'bg-[rgba(0,230,118,0.04)]',
                          )}
                        >
                          {fmtP(row.call.bid)}
                        </td>
                        <td className={clsx('tabular-nums text-text-primary px-1 text-right', callItm && 'bg-[rgba(0,230,118,0.04)]')}>
                          {fmtP(row.call.ask)}
                        </td>
                        <td className={clsx('tabular-nums text-text-secondary px-1 text-right', callItm && 'bg-[rgba(0,230,118,0.04)]')}>
                          {fmtP(row.call.last)}
                        </td>
                        <td className={clsx('tabular-nums text-text-secondary px-1 text-right', callItm && 'bg-[rgba(0,230,118,0.04)]')}>
                          {fmtNum(row.call.volume)}
                        </td>
                        <td className={clsx('tabular-nums text-text-secondary px-1 text-right', callItm && 'bg-[rgba(0,230,118,0.04)]')}>
                          {fmtNum(row.call.openInterest)}
                        </td>
                        <td className={clsx('tabular-nums px-1 text-right', ivColor(row.call.iv), callItm && 'bg-[rgba(0,230,118,0.04)]')}>
                          {fmtIV(row.call.iv)}
                        </td>
                        <td className={clsx('tabular-nums text-text-secondary px-1 text-right', callItm && 'bg-[rgba(0,230,118,0.04)]')}>
                          {fmtDelta(row.call.delta)}
                        </td>

                        {/* Strike */}
                        <td
                          className={clsx(
                            'text-center font-mono px-2 font-bold bg-bg-panel-raised tabular-nums',
                            isAtm ? 'text-accent-cyan' : 'text-text-secondary',
                          )}
                        >
                          {row.strike}
                          {isAtm && <span className="ml-1 text-accent-cyan text-2xs">ATM</span>}
                        </td>

                        {/* Put cells */}
                        <td className={clsx('tabular-nums text-text-primary px-1 text-right', putItm && 'bg-[rgba(255,23,68,0.04)]')}>
                          {fmtP(row.put.bid)}
                        </td>
                        <td className={clsx('tabular-nums text-text-primary px-1 text-right', putItm && 'bg-[rgba(255,23,68,0.04)]')}>
                          {fmtP(row.put.ask)}
                        </td>
                        <td className={clsx('tabular-nums text-text-secondary px-1 text-right', putItm && 'bg-[rgba(255,23,68,0.04)]')}>
                          {fmtP(row.put.last)}
                        </td>
                        <td className={clsx('tabular-nums text-text-secondary px-1 text-right', putItm && 'bg-[rgba(255,23,68,0.04)]')}>
                          {fmtNum(row.put.volume)}
                        </td>
                        <td className={clsx('tabular-nums text-text-secondary px-1 text-right', putItm && 'bg-[rgba(255,23,68,0.04)]')}>
                          {fmtNum(row.put.openInterest)}
                        </td>
                        <td className={clsx('tabular-nums px-1 text-right', ivColor(row.put.iv), putItm && 'bg-[rgba(255,23,68,0.04)]')}>
                          {fmtIV(row.put.iv)}
                        </td>
                        <td className={clsx('tabular-nums text-text-secondary px-1 text-right', putItm && 'bg-[rgba(255,23,68,0.04)]')}>
                          {fmtDelta(row.put.delta)}
                        </td>
                      </tr>
                    )
                  })}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer */}
      <div className="flex-shrink-0 px-3 py-1 border-t border-border-subtle flex items-center gap-4 text-2xs font-mono text-text-muted">
        <span>CALLS</span>
        <span className="text-accent-cyan">|</span>
        <span className="text-accent-cyan">{resolvedSymbol} {selectedExpiry}</span>
        <span className="text-accent-cyan">|</span>
        <span>PUTS</span>
        <span className="ml-auto">IV: COLOR CODE — <span className="text-positive">LOW</span> / <span className="text-warning">MED</span> / <span className="text-negative">HIGH</span></span>
      </div>
    </div>
  )
}

export default OptionsChain

import React, { useState } from 'react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'

// ── Types ────────────────────────────────────────────────────────────────────

type Party = 'DEM' | 'REP' | 'IND'
type TransactionType = 'BUY' | 'SELL' | 'OPTION'
type InsiderType = 'Purchase' | 'Sale' | 'Option Exercise'

export interface CongressTrade {
  id: string
  person: string
  party: Party
  chamber: 'Senate' | 'House'
  ticker: string
  transaction: TransactionType
  amountMin: number
  amountMax: number
  filedDate: Date
}

export interface InsiderTrade {
  id: string
  name: string
  title: string
  ticker: string
  shares: number
  value: number
  type: InsiderType
  date: Date
}

/**
 * Props for CongressTradePanel.
 * @prop congressTrades - Congressional disclosure data.
 * @prop insiderTrades  - Insider Form 4 data.
 * @prop loading        - Show skeleton loading state.
 */
export interface CongressTradePanelProps {
  congressTrades?: CongressTrade[]
  insiderTrades?: InsiderTrade[]
  loading?: boolean
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtValue(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000)     return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

function fmtAmountRange(min: number, max: number): string {
  return `${fmtValue(min)}–${fmtValue(max)}`
}

// ── Party badge ───────────────────────────────────────────────────────────────

const PARTY_STYLE: Record<Party, string> = {
  DEM: 'text-info border-info-dim bg-info-bg',
  REP: 'text-negative border-negative-dim bg-negative-bg',
  IND: 'text-text-secondary border-border-subtle bg-bg-panel-raised',
}

function PartyBadge({ party }: { party: Party }) {
  return (
    <span className={clsx('font-mono text-[0.48rem] px-1 py-px border rounded-sm font-bold flex-shrink-0', PARTY_STYLE[party])}>
      {party}
    </span>
  )
}

// ── Transaction badge ─────────────────────────────────────────────────────────

const TX_STYLE: Record<TransactionType, string> = {
  BUY:    'text-positive border-positive-dim bg-positive-bg',
  SELL:   'text-negative border-negative-dim bg-negative-bg',
  OPTION: 'text-accent-cyan border-[rgba(255,102,0,0.3)] bg-[rgba(255,102,0,0.1)]',
}

function TxBadge({ type }: { type: TransactionType }) {
  return (
    <span className={clsx('font-mono text-[0.5rem] px-1.5 py-px border rounded-sm font-bold flex-shrink-0', TX_STYLE[type])}>
      {type}
    </span>
  )
}

// ── Insider type badge ────────────────────────────────────────────────────────

const INSIDER_STYLE: Record<InsiderType, string> = {
  Purchase:          'text-positive border-positive-dim bg-positive-bg',
  Sale:              'text-negative border-negative-dim bg-negative-bg',
  'Option Exercise': 'text-accent-cyan border-[rgba(255,102,0,0.3)] bg-[rgba(255,102,0,0.1)]',
}

function InsiderBadge({ type }: { type: InsiderType }) {
  const short: Record<InsiderType, string> = {
    Purchase: 'BUY', Sale: 'SELL', 'Option Exercise': 'OPT',
  }
  return (
    <span className={clsx('font-mono text-[0.5rem] px-1 py-px border rounded-sm font-bold flex-shrink-0', INSIDER_STYLE[type])}>
      {short[type]}
    </span>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CongressTradePanel({
  congressTrades = [],
  insiderTrades = [],
  loading = false,
}: CongressTradePanelProps) {
  const [activeTab, setActiveTab] = useState<'CONGRESS' | 'INSIDER'>('CONGRESS')

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="panel-header"><span>◈ Congress/Insider Trades</span></div>
        <div className="p-2 space-y-1.5">
          {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-8 skeleton rounded-sm" />)}
        </div>
      </div>
    )
  }

  if (!congressTrades.length && !insiderTrades.length) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="panel-header"><span className="flex-1">◈ Congress/Insider Trades</span></div>
        <div className="flex items-center justify-center flex-1 text-text-muted font-mono text-[0.65rem]">
          <div className="text-center">
            <div className="text-text-dim mb-1">NO DATA</div>
            <div className="text-[0.55rem]">Congressional trading data requires QuiverQuant API integration</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Congress/Insider Trades</span>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border-subtle flex-shrink-0">
        {(['CONGRESS', 'INSIDER'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={clsx(
              'flex-1 font-mono text-[0.6rem] py-1.5 transition-colors border-b-2',
              activeTab === tab
                ? 'text-accent-cyan border-accent-cyan bg-[rgba(255,102,0,0.04)]'
                : 'text-text-muted border-transparent hover:text-text-secondary',
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Congress tab */}
      {activeTab === 'CONGRESS' && (
        <div className="flex-1 overflow-y-auto min-h-0">
          <table className="data-table w-full">
            <thead>
              <tr>
                <th className="text-left pl-2.5">Member</th>
                <th className="text-left">Ticker</th>
                <th>Type</th>
                <th>Amount</th>
                <th>Filed</th>
              </tr>
            </thead>
            <tbody>
              {congressTrades.map(trade => {
                const daysAgo = Math.round((Date.now() - trade.filedDate.getTime()) / (24 * 3600 * 1000))
                return (
                  <tr key={trade.id} className="hover:bg-bg-panel-hover transition-colors">
                    <td className="text-left pl-2.5">
                      <div className="flex items-center gap-1.5">
                        <PartyBadge party={trade.party} />
                        <span className="text-text-primary truncate max-w-[90px]">{trade.person}</span>
                        <span className="font-mono text-[0.5rem] text-text-muted">{trade.chamber.slice(0, 3)}</span>
                      </div>
                    </td>
                    <td className="text-left font-bold text-accent-cyan">{trade.ticker}</td>
                    <td><TxBadge type={trade.transaction} /></td>
                    <td className="tabular-nums text-text-secondary text-[0.6rem]">
                      {fmtAmountRange(trade.amountMin, trade.amountMax)}
                    </td>
                    <td className="text-text-muted tabular-nums">
                      {daysAgo}d ago
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Insider tab */}
      {activeTab === 'INSIDER' && (
        <div className="flex-1 overflow-y-auto min-h-0">
          <table className="data-table w-full">
            <thead>
              <tr>
                <th className="text-left pl-2.5">Name</th>
                <th className="text-left">Ticker</th>
                <th>Shares</th>
                <th>Value</th>
                <th>Type</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {insiderTrades.map(trade => {
                const isLargeBuy = trade.type === 'Purchase' && trade.value >= 1_000_000
                const daysAgo = Math.round((Date.now() - trade.date.getTime()) / (24 * 3600 * 1000))
                return (
                  <tr
                    key={trade.id}
                    className={clsx(
                      'hover:bg-bg-panel-hover transition-colors',
                      isLargeBuy && 'border-l-2 border-l-accent-cyan',
                    )}
                  >
                    <td className="text-left pl-2.5">
                      <div>
                        <div className="text-text-primary truncate max-w-[100px]">{trade.name}</div>
                        <div className="font-mono text-[0.5rem] text-text-muted">{trade.title}</div>
                      </div>
                    </td>
                    <td className="text-left font-bold text-accent-cyan">{trade.ticker}</td>
                    <td className="tabular-nums">
                      {trade.shares > 0 ? trade.shares.toLocaleString() : '—'}
                    </td>
                    <td className={clsx('tabular-nums font-semibold', isLargeBuy ? 'text-accent-cyan' : 'text-text-primary')}>
                      {fmtValue(trade.value)}
                    </td>
                    <td><InsiderBadge type={trade.type} /></td>
                    <td className="text-text-muted tabular-nums">{daysAgo}d ago</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

import React from 'react'
import clsx from 'clsx'
import type { Position } from '@/types/portfolio'
import ContextMenu, { useContextMenu, POSITION_CONTEXT_ITEMS } from '@/components/shared/ContextMenu'
import VirtualTable from '@/components/shared/VirtualTable'
import type { VirtualColumnDef } from '@/components/shared/VirtualTable'

interface PositionsGridProps {
  positions: Position[]
  onPositionClose?: (symbol: string) => void
  selectedSymbol?: string
  onSymbolSelect?: (symbol: string) => void
  loading?: boolean
}

function fmt$(value: number): string {
  const abs = Math.abs(value)
  const s = value >= 0 ? '+' : '-'
  if (abs >= 1_000_000) return `${s}$${(abs / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000)     return `${s}$${(abs / 1_000).toFixed(1)}K`
  return `${s}$${abs.toFixed(0)}`
}

function fmtPct(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

const COLS = ['SYMBOL', 'QTY', 'COST', 'LAST', 'UNREAL P&L', '%', 'DAY P&L', '% PORT', '']

// VirtualTable requires T extends Record<string, unknown>. Position is a plain
// interface that is structurally compatible; we cast at the call site.
type PositionRow = Position & Record<string, unknown>

/**
 * Column definitions for VirtualTable. These mirror every data column in the
 * existing positions table so the visual output is identical.
 *
 * NOTE: VirtualTable does not expose onContextMenu on rows — it only supports
 * onRowClick. Therefore the right-click context menu is intentionally omitted
 * in the VirtualTable code path (> 20 positions). The standard table below
 * (the fallback for <= 20 positions) retains the full context menu behaviour.
 * A future enhancement could extend VirtualTable with an onRowContextMenu prop.
 *
 * The close-position button (last column) is also omitted in the VirtualTable
 * path because VirtualTable has no concept of a hover-reveal action button and
 * the column would always be visible without the group-hover mechanism. Users
 * with > 20 positions can still close positions via the panel's row click
 * (onSymbolSelect) or another control outside this table.
 */
function buildVirtualPositionColumns(
  onPositionClose: ((symbol: string) => void) | undefined
): VirtualColumnDef<PositionRow>[] {
  return [
    {
      key: 'symbol',
      header: 'SYMBOL',
      accessor: (row: PositionRow) => (
        <div className="flex items-center gap-1.5">
          <span className={clsx(
            'font-mono text-[0.58rem] font-semibold px-0.5 rounded-sm',
            row.side === 'LONG' ? 'text-positive bg-positive-bg' : 'text-negative bg-negative-bg'
          )}>
            {row.side === 'LONG' ? 'L' : 'S'}
          </span>
          <span className="font-mono text-[0.72rem] font-semibold text-accent-cyan tracking-wide">
            {row.symbol as string}
          </span>
        </div>
      ),
      align: 'left',
      width: '80px',
    },
    {
      key: 'quantity',
      header: 'QTY',
      accessor: (row: PositionRow) => (
        <span className="font-mono text-[0.7rem] tabular-nums text-text-primary">
          {(row.quantity as number).toLocaleString()}
        </span>
      ),
      align: 'right',
      width: '56px',
    },
    {
      key: 'avgCostBasis',
      header: 'COST',
      accessor: (row: PositionRow) => (
        <span className="font-mono text-[0.7rem] tabular-nums text-text-secondary">
          {(row.avgCostBasis as number).toFixed(2)}
        </span>
      ),
      align: 'right',
      width: '60px',
    },
    {
      key: 'currentPrice',
      header: 'LAST',
      accessor: (row: PositionRow) => (
        <span className="font-mono text-[0.7rem] tabular-nums text-text-primary font-medium">
          {(row.currentPrice as number).toFixed(2)}
        </span>
      ),
      align: 'right',
      width: '60px',
    },
    {
      key: 'unrealizedPnl',
      header: 'UNREAL P&L',
      accessor: (row: PositionRow) => (
        <span className={clsx(
          'font-mono text-[0.7rem] tabular-nums font-semibold',
          (row.unrealizedPnl as number) >= 0 ? 'text-positive' : 'text-negative'
        )}>
          {fmt$(row.unrealizedPnl as number)}
        </span>
      ),
      align: 'right',
      width: '72px',
    },
    {
      key: 'unrealizedPnlPercent',
      header: '%',
      accessor: (row: PositionRow) => (
        <span className={clsx(
          'font-mono text-[0.65rem] tabular-nums',
          (row.unrealizedPnl as number) >= 0 ? 'text-positive' : 'text-negative'
        )}>
          {fmtPct(row.unrealizedPnlPercent as number)}
        </span>
      ),
      align: 'right',
      width: '52px',
    },
    {
      key: 'dayPnl',
      header: 'DAY P&L',
      accessor: (row: PositionRow) => (
        <span className={clsx(
          'font-mono text-[0.7rem] tabular-nums',
          (row.dayPnl as number) >= 0 ? 'text-positive' : 'text-negative'
        )}>
          {fmt$(row.dayPnl as number)}
        </span>
      ),
      align: 'right',
      width: '68px',
    },
    {
      key: 'weight',
      header: '% PORT',
      accessor: (row: PositionRow) => (
        <span className="font-mono text-[0.65rem] tabular-nums text-text-muted">
          {(row.weight as number).toFixed(1)}%
        </span>
      ),
      align: 'right',
      width: '52px',
    },
    // Close button column — only rendered when onPositionClose is provided.
    // Note: group-hover is not available inside VirtualTable rows, so the
    // button is always visible (not opacity-0 / group-hover:opacity-100).
    ...(onPositionClose != null
      ? [{
          key: 'close',
          header: '',
          accessor: (row: PositionRow) => (
            <button
              onClick={(e: React.MouseEvent) => {
                e.stopPropagation()
                onPositionClose(row.symbol as string)
              }}
              className="font-mono text-[0.55rem] px-1 py-px border border-negative-dim text-negative hover:bg-negative-bg transition-all rounded-sm"
            >
              ✕
            </button>
          ),
          align: 'center' as const,
          width: '32px',
        }]
      : []
    ),
  ]
}

/** Threshold above which VirtualTable is used instead of the standard table. */
const VIRTUAL_POSITION_THRESHOLD = 20

export default function PositionsGrid({
  positions,
  onPositionClose,
  selectedSymbol,
  onSymbolSelect,
  loading = false,
}: PositionsGridProps) {
  const ctxMenu = useContextMenu()
  const totalUnreal = positions.reduce((s, p) => s + p.unrealizedPnl, 0)
  const totalDay = positions.reduce((s, p) => s + p.dayPnl, 0)
  const totalVal = positions.reduce((s, p) => s + p.marketValue, 0)

  if (loading) {
    return (
      <div className="p-2 space-y-1">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-7 skeleton rounded-sm" />
        ))}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Panel Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Positions</span>
        <span className="font-mono text-[0.6rem] text-text-muted mr-2">{positions.length} open</span>
        {totalVal > 0 && (
          <span className="font-mono text-[0.6rem] text-text-secondary tabular-nums">
            ${totalVal.toLocaleString('en-US', { maximumFractionDigits: 0 })}
          </span>
        )}
      </div>

      {/* Summary Bar */}
      {positions.length > 0 && (
        <div className="flex items-center gap-4 px-2.5 py-1.5 border-b border-border-subtle bg-bg-panel flex-shrink-0">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[0.55rem] text-text-muted uppercase">Unreal P&L</span>
            <span className={clsx('font-mono text-[0.68rem] tabular-nums font-semibold', totalUnreal >= 0 ? 'text-positive' : 'text-negative')}>
              {fmt$(totalUnreal)}
            </span>
          </div>
          <div className="w-px h-3 bg-border-subtle" />
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[0.55rem] text-text-muted uppercase">Day P&L</span>
            <span className={clsx('font-mono text-[0.68rem] tabular-nums font-semibold', totalDay >= 0 ? 'text-positive' : 'text-negative')}>
              {fmt$(totalDay)}
            </span>
          </div>
        </div>
      )}

      {/* Table — VirtualTable for large datasets (> 20 rows), standard table otherwise */}
      {positions.length > VIRTUAL_POSITION_THRESHOLD ? (
        <VirtualTable<PositionRow>
          columns={buildVirtualPositionColumns(onPositionClose)}
          data={positions as PositionRow[]}
          rowHeight={28}
          rowKey={(row: PositionRow) => row.symbol as string}
          selectedId={selectedSymbol}
          onRowClick={(row: PositionRow) => onSymbolSelect?.(row.symbol as string)}
          emptyMessage="No open positions"
          className="flex-1 min-h-0"
        />
      ) : (
        <div className="flex-1 overflow-auto min-h-0">
          <table className="data-table">
            <thead>
              <tr>
                {COLS.map((col, i) => (
                  <th key={col + i} className={clsx(i === 0 ? 'text-left pl-2.5' : '', i === 8 ? 'w-8' : '')}>
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-8 text-text-muted font-mono text-xs">
                    No open positions
                  </td>
                </tr>
              ) : (
                positions.map(pos => {
                  const pnlColor = pos.unrealizedPnl >= 0 ? 'text-positive' : 'text-negative'
                  const dayColor = pos.dayPnl >= 0 ? 'text-positive' : 'text-negative'
                  const selected = pos.symbol === selectedSymbol

                  return (
                    <tr
                      key={pos.symbol}
                      className={clsx('cursor-pointer group', selected ? 'selected' : '')}
                      onClick={() => onSymbolSelect?.(pos.symbol)}
                      onContextMenu={e => ctxMenu.onOpen(e, POSITION_CONTEXT_ITEMS({
                        onClose: () => onPositionClose?.(pos.symbol),
                        onAddToSize: () => {},
                        onReduceSize: () => {},
                        onViewDetails: () => onSymbolSelect?.(pos.symbol),
                      }))}
                    >
                      <td className="pl-2.5">
                        <div className="flex items-center gap-1.5">
                          <span className={clsx('font-mono text-[0.58rem] font-semibold px-0.5 rounded-sm', pos.side === 'LONG' ? 'text-positive bg-positive-bg' : 'text-negative bg-negative-bg')}>
                            {pos.side === 'LONG' ? 'L' : 'S'}
                          </span>
                          <span className="font-mono text-[0.72rem] font-semibold text-accent-cyan tracking-wide">
                            {pos.symbol}
                          </span>
                        </div>
                      </td>
                      <td className="font-mono text-[0.7rem] tabular-nums text-text-primary">
                        {pos.quantity.toLocaleString()}
                      </td>
                      <td className="font-mono text-[0.7rem] tabular-nums text-text-secondary">
                        {pos.avgCostBasis.toFixed(2)}
                      </td>
                      <td className="font-mono text-[0.7rem] tabular-nums text-text-primary font-medium">
                        {pos.currentPrice.toFixed(2)}
                      </td>
                      <td className={clsx('font-mono text-[0.7rem] tabular-nums font-semibold', pnlColor)}>
                        {fmt$(pos.unrealizedPnl)}
                      </td>
                      <td className={clsx('font-mono text-[0.65rem] tabular-nums', pnlColor)}>
                        {fmtPct(pos.unrealizedPnlPercent)}
                      </td>
                      <td className={clsx('font-mono text-[0.7rem] tabular-nums', dayColor)}>
                        {fmt$(pos.dayPnl)}
                      </td>
                      <td className="font-mono text-[0.65rem] tabular-nums text-text-muted">
                        {pos.weight.toFixed(1)}%
                      </td>
                      <td className="pr-2">
                        {onPositionClose && (
                          <button
                            onClick={e => { e.stopPropagation(); onPositionClose(pos.symbol) }}
                            className="opacity-0 group-hover:opacity-100 font-mono text-[0.55rem] px-1 py-px border border-negative-dim text-negative hover:bg-negative-bg transition-all rounded-sm"
                          >
                            ✕
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      <ContextMenu
        open={ctxMenu.open}
        position={ctxMenu.position}
        items={ctxMenu.items}
        onClose={ctxMenu.onClose}
      />
    </div>
  )
}

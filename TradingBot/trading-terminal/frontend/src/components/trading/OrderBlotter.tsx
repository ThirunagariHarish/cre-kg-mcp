import React, { useState, useMemo } from 'react'
import clsx from 'clsx'
import { format } from 'date-fns'
import { ScrollText } from 'lucide-react'
import type { Order, OrderStatus, OrderSide } from '@/types/orders'
import VirtualTable from '@/components/shared/VirtualTable'
import type { VirtualColumnDef } from '@/components/shared/VirtualTable'

const STATUS_STYLES: Record<OrderStatus, string> = {
  PENDING: 'text-warning border-warning-dim bg-warning-bg',
  SUBMITTED: 'text-accent-cyan border-accent-cyan-dim bg-info-bg',
  PARTIALLY_FILLED: 'text-accent-cyan border-accent-cyan-dim bg-info-bg',
  FILLED: 'text-positive border-positive-dim bg-positive-bg',
  CANCELLED: 'text-text-muted border-border-subtle bg-bg-panel-raised',
  REJECTED: 'text-negative border-negative-dim bg-negative-bg',
  EXPIRED: 'text-text-muted border-border-muted bg-bg-panel-raised',
  HELD: 'text-warning border-warning-dim bg-warning-bg',
}

interface OrderRowProps {
  order: Order
  selected: boolean
  onSelect: () => void
}

function OrderRow({ order, selected, onSelect }: OrderRowProps) {
  const isBuy = order.side === 'BUY'
  const pnlColor = (order.filledValue ?? 0) > 0 ? 'text-positive' : 'text-negative'
  const timeStr = format(order.submittedAt, 'HH:mm:ss')
  const fillPct = order.quantity > 0
    ? Math.round((order.filledQuantity / order.quantity) * 100)
    : 0

  return (
    <tr
      className={clsx(
        'cursor-pointer border-b border-border-muted transition-colors',
        selected
          ? 'bg-[rgba(56,189,248,0.08)]'
          : 'hover:bg-bg-panel-hover'
      )}
      onClick={onSelect}
    >
      {/* Time */}
      <td className="pl-2 pr-1 py-1 text-left font-mono text-[0.6rem] text-text-muted tabular-nums whitespace-nowrap">
        {timeStr}
      </td>

      {/* Symbol */}
      <td className="px-1 py-1 text-left font-mono text-[0.7rem] font-semibold text-accent-cyan">
        {order.symbol}
      </td>

      {/* Side */}
      <td className="px-1 py-1 text-center">
        <span className={clsx(
          'font-mono text-[0.6rem] font-semibold px-1 py-px rounded-sm',
          isBuy ? 'text-positive' : 'text-negative'
        )}>
          {isBuy ? '▲' : '▼'} {order.side}
        </span>
      </td>

      {/* Qty */}
      <td className="px-1 py-1 text-right font-mono text-[0.7rem] tabular-nums text-text-primary">
        {order.quantity.toLocaleString()}
      </td>

      {/* Type */}
      <td className="px-1 py-1 text-center font-mono text-[0.6rem] text-text-secondary">
        {order.type}
      </td>

      {/* Price */}
      <td className="px-1 py-1 text-right font-mono text-[0.7rem] tabular-nums text-text-primary">
        {order.limitPrice
          ? `$${order.limitPrice.toFixed(2)}`
          : <span className="text-text-muted">MKT</span>
        }
      </td>

      {/* Status */}
      <td className="px-1 py-1 text-center">
        <span className={clsx(
          'font-mono text-[0.55rem] uppercase px-1 py-px rounded-sm border',
          STATUS_STYLES[order.status]
        )}>
          {order.status.replace('_', ' ')}
        </span>
      </td>

      {/* Filled */}
      <td className="px-1 py-1 text-right font-mono text-[0.6rem] tabular-nums text-text-secondary">
        {order.filledQuantity > 0 ? (
          <span>
            {order.filledQuantity.toLocaleString()}
            {fillPct < 100 && (
              <span className="text-text-muted ml-0.5 text-[0.55rem]">
                ({fillPct}%)
              </span>
            )}
          </span>
        ) : (
          <span className="text-text-muted">—</span>
        )}
      </td>

      {/* Avg Fill Price */}
      <td className="px-1 pr-2 py-1 text-right font-mono text-[0.7rem] tabular-nums text-text-primary">
        {order.avgFillPrice
          ? `$${order.avgFillPrice.toFixed(2)}`
          : <span className="text-text-muted">—</span>
        }
      </td>
    </tr>
  )
}

interface OrderBlotterProps {
  orders: Order[]
  selectedOrderId?: string
  onOrderSelect?: (order: Order) => void
  loading?: boolean
}

const STATUS_FILTERS: (OrderStatus | 'ALL')[] = ['ALL', 'PENDING', 'FILLED', 'REJECTED', 'CANCELLED']

// VirtualTable requires T extends Record<string, unknown>. Order is a plain
// interface that is structurally compatible; we cast at the call site.
type OrderRow = Order & Record<string, unknown>

/**
 * Column definitions for VirtualTable. These mirror every column in the
 * existing OrderRow component so the visual output is identical.
 * Used only when filtered.length > 50 (fallback threshold).
 */
const VIRTUAL_ORDER_COLUMNS: VirtualColumnDef<OrderRow>[] = [
  {
    key: 'time',
    header: 'TIME',
    accessor: (row: OrderRow) => (
      <span className="font-mono text-[0.6rem] text-text-muted tabular-nums">
        {format(row.submittedAt as number, 'HH:mm:ss')}
      </span>
    ),
    align: 'left',
    width: '60px',
  },
  {
    key: 'symbol',
    header: 'SYMBOL',
    accessor: (row: OrderRow) => (
      <span className="font-mono text-[0.7rem] font-semibold text-accent-cyan">
        {row.symbol as string}
      </span>
    ),
    align: 'left',
    width: '64px',
  },
  {
    key: 'side',
    header: 'SIDE',
    accessor: (row: OrderRow) => {
      const isBuy = row.side === 'BUY'
      return (
        <span className={clsx(
          'font-mono text-[0.6rem] font-semibold px-1 py-px rounded-sm',
          isBuy ? 'text-positive' : 'text-negative'
        )}>
          {isBuy ? '▲' : '▼'} {row.side as string}
        </span>
      )
    },
    align: 'center',
    width: '52px',
  },
  {
    key: 'quantity',
    header: 'QTY',
    accessor: (row: OrderRow) => (
      <span className="font-mono text-[0.7rem] tabular-nums text-text-primary">
        {(row.quantity as number).toLocaleString()}
      </span>
    ),
    align: 'right',
    width: '56px',
  },
  {
    key: 'type',
    header: 'TYPE',
    accessor: (row: OrderRow) => (
      <span className="font-mono text-[0.6rem] text-text-secondary">
        {row.type as string}
      </span>
    ),
    align: 'center',
    width: '64px',
  },
  {
    key: 'price',
    header: 'PRICE',
    accessor: (row: OrderRow) => {
      const limitPrice = row.limitPrice as number | undefined
      return limitPrice != null
        ? <span className="font-mono text-[0.7rem] tabular-nums text-text-primary">${limitPrice.toFixed(2)}</span>
        : <span className="font-mono text-[0.7rem] text-text-muted">MKT</span>
    },
    align: 'right',
    width: '64px',
  },
  {
    key: 'status',
    header: 'STATUS',
    accessor: (row: OrderRow) => (
      <span className={clsx(
        'font-mono text-[0.55rem] uppercase px-1 py-px rounded-sm border',
        STATUS_STYLES[row.status as OrderStatus]
      )}>
        {(row.status as string).replace('_', ' ')}
      </span>
    ),
    align: 'center',
    width: '80px',
  },
  {
    key: 'filled',
    header: 'FILLED',
    accessor: (row: OrderRow) => {
      const filled = row.filledQuantity as number
      const qty = row.quantity as number
      const fillPct = qty > 0 ? Math.round((filled / qty) * 100) : 0
      return filled > 0 ? (
        <span className="font-mono text-[0.6rem] tabular-nums text-text-secondary">
          {filled.toLocaleString()}
          {fillPct < 100 && (
            <span className="text-text-muted ml-0.5 text-[0.55rem]">
              ({fillPct}%)
            </span>
          )}
        </span>
      ) : (
        <span className="font-mono text-[0.6rem] text-text-muted">—</span>
      )
    },
    align: 'right',
    width: '72px',
  },
  {
    key: 'avgFillPrice',
    header: 'AVG FILL',
    accessor: (row: OrderRow) => {
      const avg = row.avgFillPrice as number | undefined
      return avg != null
        ? <span className="font-mono text-[0.7rem] tabular-nums text-text-primary">${avg.toFixed(2)}</span>
        : <span className="font-mono text-[0.7rem] text-text-muted">—</span>
    },
    align: 'right',
    width: '72px',
  },
]

/** Threshold above which VirtualTable is used instead of the standard table. */
const VIRTUAL_ORDER_THRESHOLD = 50

export default function OrderBlotter({
  orders,
  selectedOrderId,
  onOrderSelect,
  loading = false,
}: OrderBlotterProps) {
  const [statusFilter, setStatusFilter] = useState<OrderStatus | 'ALL'>('ALL')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [sideFilter, setSideFilter] = useState<OrderSide | 'ALL'>('ALL')

  const filtered = useMemo(() => {
    return orders.filter(o => {
      if (statusFilter !== 'ALL' && o.status !== statusFilter) return false
      if (sideFilter !== 'ALL' && o.side !== sideFilter) return false
      if (symbolFilter && !o.symbol.toUpperCase().includes(symbolFilter.toUpperCase())) return false
      return true
    })
  }, [orders, statusFilter, sideFilter, symbolFilter])

  // Stats
  const filledCount = orders.filter(o => o.status === 'FILLED').length
  const pendingCount = orders.filter(o => o.status === 'PENDING' || o.status === 'SUBMITTED').length

  if (loading) {
    return (
      <div className="flex flex-col gap-0.5 p-2">
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="h-7 skeleton rounded-sm" />
        ))}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Panel Header */}
      <div className="panel-header">
        <ScrollText size={10} className="text-accent-cyan flex-shrink-0" />
        <span className="flex-1">◈ Order Blotter</span>
        <span className="font-mono text-[0.55rem] text-positive">{filledCount}F</span>
        <span className="font-mono text-[0.55rem] text-warning ml-1">{pendingCount}P</span>
        <span className="font-mono text-[0.55rem] text-text-muted ml-1">{orders.length} total</span>
      </div>

      {/* Filter Bar */}
      <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-border-subtle flex-shrink-0 flex-wrap">
        {/* Symbol filter */}
        <input
          type="text"
          value={symbolFilter}
          onChange={e => setSymbolFilter(e.target.value.toUpperCase())}
          placeholder="SYMBOL"
          className="terminal-input h-5 w-16 text-[0.6rem] uppercase"
        />

        {/* Status filters */}
        {STATUS_FILTERS.map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={clsx(
              'font-mono text-[0.55rem] uppercase px-1.5 py-0.5 rounded-sm border transition-colors',
              statusFilter === s
                ? 'border-accent-cyan text-accent-cyan bg-info-bg'
                : 'border-border-subtle text-text-muted hover:border-border-active'
            )}
          >
            {s}
          </button>
        ))}

        {/* Side filters */}
        {(['ALL', 'BUY', 'SELL'] as const).map(s => (
          <button
            key={s}
            onClick={() => setSideFilter(s)}
            className={clsx(
              'font-mono text-[0.55rem] uppercase px-1 py-0.5 rounded-sm border transition-colors',
              sideFilter === s
                ? s === 'BUY' ? 'border-positive text-positive bg-positive-bg'
                  : s === 'SELL' ? 'border-negative text-negative bg-negative-bg'
                  : 'border-accent-cyan text-accent-cyan bg-info-bg'
                : 'border-border-subtle text-text-muted hover:border-border-active'
            )}
          >
            {s}
          </button>
        ))}

        <span className="flex-1" />

        {/* Stats */}
        <span className="font-mono text-[0.55rem] text-positive">{filledCount}F</span>
        <span className="font-mono text-[0.55rem] text-warning">{pendingCount}P</span>
        <span className="font-mono text-[0.55rem] text-text-muted">{filtered.length}/{orders.length}</span>
      </div>

      {/* Table — VirtualTable for large datasets (> 50 rows), standard table otherwise */}
      {filtered.length > VIRTUAL_ORDER_THRESHOLD ? (
        <VirtualTable<OrderRow>
          columns={VIRTUAL_ORDER_COLUMNS}
          data={filtered as OrderRow[]}
          rowHeight={28}
          rowKey={(row: OrderRow) => row.id as string}
          selectedId={selectedOrderId}
          onRowClick={(row: OrderRow) => onOrderSelect?.(row as unknown as Order)}
          emptyMessage="No orders"
          className="flex-1 min-h-0"
        />
      ) : (
        <div className="flex-1 overflow-auto min-h-0">
          <table className="w-full border-collapse">
            <thead>
              <tr className="sticky top-0 bg-bg-panel z-raised">
                {['TIME', 'SYMBOL', 'SIDE', 'QTY', 'TYPE', 'PRICE', 'STATUS', 'FILLED', 'AVG FILL'].map((col, i) => (
                  <th
                    key={col}
                    className={clsx(
                      'py-1 font-mono text-[0.55rem] uppercase tracking-widest text-text-muted',
                      'border-b border-border-subtle whitespace-nowrap select-none',
                      i === 0 || i === 1 ? 'pl-2 text-left' : 'px-1 text-right',
                      i === 2 || i === 4 || i === 6 ? 'text-center' : ''
                    )}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-8 text-text-muted font-mono text-xs">
                    No orders
                  </td>
                </tr>
              ) : (
                filtered.map(order => (
                  <OrderRow
                    key={order.id}
                    order={order}
                    selected={order.id === selectedOrderId}
                    onSelect={() => onOrderSelect?.(order)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

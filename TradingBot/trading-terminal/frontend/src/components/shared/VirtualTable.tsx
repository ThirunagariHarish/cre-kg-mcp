import React, { useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import clsx from 'clsx'

// ── Column definition ─────────────────────────────────────────────────────────

export interface VirtualColumnDef<T = unknown> {
  key: string
  header: string
  accessor: keyof T | ((row: T) => React.ReactNode)
  align?: 'left' | 'right' | 'center'
  width?: string
  minWidth?: string
  className?: string
  headerClassName?: string
  render?: (value: unknown, row: T) => React.ReactNode
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface VirtualTableProps<T extends Record<string, unknown>> {
  /** Column definitions */
  columns: VirtualColumnDef<T>[]
  /** Row data — supports 10,000+ rows */
  data: T[]
  /** Fixed row height in pixels (required for virtualization) */
  rowHeight?: number
  /** Callback when a row is clicked */
  onRowClick?: (row: T) => void
  /** Key of the currently selected row */
  selectedId?: string
  /** Row key accessor */
  rowKey?: keyof T | ((row: T) => string)
  /** Extra class on the outer container */
  className?: string
  /** Message shown when data is empty */
  emptyMessage?: string
}

const HEADER_HEIGHT = 28

// ── Main Component ────────────────────────────────────────────────────────────

function VirtualTable<T extends Record<string, unknown>>({
  columns,
  data,
  rowHeight = 28,
  onRowClick,
  selectedId,
  rowKey = 'id' as keyof T,
  className,
  emptyMessage = 'No data',
}: VirtualTableProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null)

  const rowVirtualizer = useVirtualizer({
    count: data.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 10,
  })

  function getRowKey(row: T): string {
    if (typeof rowKey === 'function') return rowKey(row)
    return String(row[rowKey] ?? '')
  }

  function getCellContent(col: VirtualColumnDef<T>, row: T): React.ReactNode {
    if (typeof col.accessor === 'function') {
      return col.accessor(row)
    }
    const value = row[col.accessor as keyof T]
    if (col.render) return col.render(value, row)
    return String(value ?? '—')
  }

  const totalSize = rowVirtualizer.getTotalSize()
  const virtualItems = rowVirtualizer.getVirtualItems()

  return (
    <div className={clsx('flex flex-col border border-border-subtle rounded-sm overflow-hidden', className)}>
      {/* Sticky header */}
      <div
        className="flex-shrink-0 bg-bg-panel border-b border-border-subtle"
        style={{ height: HEADER_HEIGHT }}
      >
        <table className="w-full border-collapse table-fixed">
          <colgroup>
            {columns.map(col => (
              <col
                key={col.key}
                style={{ width: col.width, minWidth: col.minWidth }}
              />
            ))}
          </colgroup>
          <thead>
            <tr>
              {columns.map(col => (
                <th
                  key={col.key}
                  className={clsx(
                    'font-mono text-[0.55rem] uppercase tracking-widest text-text-muted whitespace-nowrap',
                    'py-1 px-1.5',
                    col.align === 'left' ? 'text-left'
                      : col.align === 'center' ? 'text-center'
                      : 'text-right',
                    col.headerClassName,
                  )}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
        </table>
      </div>

      {/* Virtualized scroll container */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-auto"
        role="grid"
        aria-label="Virtual data table"
      >
        {data.length === 0 ? (
          <div className="flex items-center justify-center py-12">
            <span className="font-mono text-xs text-text-muted">{emptyMessage}</span>
          </div>
        ) : (
          <div
            style={{ height: totalSize, position: 'relative' }}
          >
            {virtualItems.map(virtualRow => {
              const row = data[virtualRow.index]
              const key = getRowKey(row)
              const isSelected = selectedId === key

              return (
                <div
                  key={virtualRow.key}
                  role="row"
                  aria-selected={isSelected}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    height: rowHeight,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                  className={clsx(
                    'flex border-b border-border-muted transition-colors',
                    onRowClick && 'cursor-pointer',
                    isSelected
                      ? 'bg-[rgba(255,102,0,0.08)]'
                      : onRowClick ? 'hover:bg-bg-panel-hover' : '',
                  )}
                  onClick={() => onRowClick?.(row)}
                >
                  <table className="w-full border-collapse table-fixed">
                    <colgroup>
                      {columns.map(col => (
                        <col
                          key={col.key}
                          style={{ width: col.width, minWidth: col.minWidth }}
                        />
                      ))}
                    </colgroup>
                    <tbody>
                      <tr style={{ height: rowHeight }}>
                        {columns.map(col => (
                          <td
                            key={col.key}
                            role="gridcell"
                            className={clsx(
                              'font-mono text-[0.7rem] tabular-nums whitespace-nowrap text-text-primary',
                              'py-0 px-1.5',
                              col.align === 'left' ? 'text-left'
                                : col.align === 'center' ? 'text-center'
                                : 'text-right',
                              col.className,
                            )}
                          >
                            {getCellContent(col, row)}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default VirtualTable

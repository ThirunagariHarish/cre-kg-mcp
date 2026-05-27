import React, { useState, useMemo, useRef, useCallback } from 'react'
import clsx from 'clsx'
import { ChevronUp, ChevronDown } from 'lucide-react'

export interface ColumnDef<T = unknown> {
  key: string
  header: string
  accessor: keyof T | ((row: T) => React.ReactNode)
  align?: 'left' | 'right' | 'center'
  width?: string
  minWidth?: string
  sortable?: boolean
  className?: string
  headerClassName?: string
  render?: (value: unknown, row: T) => React.ReactNode
}

interface DataTableProps<T extends Record<string, unknown>> {
  columns: ColumnDef<T>[]
  data: T[]
  onRowClick?: (row: T) => void
  selectedRowKey?: string
  rowKey?: keyof T | ((row: T) => string)
  loading?: boolean
  emptyMessage?: string
  stickyHeader?: boolean
  compact?: boolean
  className?: string
}

type SortConfig = { key: string; dir: 'asc' | 'desc' }

function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  onRowClick,
  selectedRowKey,
  rowKey = 'id' as keyof T,
  loading = false,
  emptyMessage = 'No data',
  stickyHeader = true,
  compact = false,
  className,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<SortConfig | null>(null)

  const getRowKey = useCallback((row: T): string => {
    if (typeof rowKey === 'function') return rowKey(row)
    return String(row[rowKey] ?? '')
  }, [rowKey])

  const sorted = useMemo(() => {
    if (!sort) return data
    return [...data].sort((a, b) => {
      const col = columns.find(c => c.key === sort.key)
      if (!col) return 0

      let av: unknown, bv: unknown
      if (typeof col.accessor === 'function') {
        return 0 // can't sort render functions
      } else {
        av = a[col.accessor as keyof T]
        bv = b[col.accessor as keyof T]
      }

      if (av === bv) return 0
      if (av === undefined || av === null) return 1
      if (bv === undefined || bv === null) return -1

      const cmp = typeof av === 'string' && typeof bv === 'string'
        ? av.localeCompare(bv)
        : (Number(av) - Number(bv))

      return sort.dir === 'asc' ? cmp : -cmp
    })
  }, [data, sort, columns])

  const handleSort = (key: string) => {
    setSort(prev =>
      prev?.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' }
    )
  }

  const cellPadding = compact ? 'py-0.5 px-1.5' : 'py-1 px-2'
  const rowHeight = compact ? 'h-6' : 'h-7'

  if (loading) {
    return (
      <div className="flex flex-col gap-0.5 p-1.5">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className={clsx('skeleton rounded-sm', compact ? 'h-5' : 'h-6')} />
        ))}
      </div>
    )
  }

  return (
    <div className={clsx('overflow-auto', className)}>
      <table className="w-full border-collapse">
        <thead>
          <tr
            className={clsx(
              stickyHeader && 'sticky top-0 z-raised',
              'bg-bg-panel'
            )}
          >
            {columns.map(col => (
              <th
                key={col.key}
                className={clsx(
                  'font-mono text-[0.55rem] uppercase tracking-widest text-text-muted',
                  'border-b border-border-subtle whitespace-nowrap',
                  cellPadding,
                  col.align === 'left' ? 'text-left' : col.align === 'center' ? 'text-center' : 'text-right',
                  col.sortable && 'cursor-pointer hover:text-text-primary select-none',
                  sort?.key === col.key && 'text-accent-cyan',
                  col.headerClassName
                )}
                style={{ width: col.width, minWidth: col.minWidth }}
                onClick={col.sortable ? () => handleSort(col.key) : undefined}
              >
                <span className="flex items-center gap-0.5 justify-inherit">
                  {col.header}
                  {col.sortable && sort?.key === col.key && (
                    sort.dir === 'asc'
                      ? <ChevronUp size={8} />
                      : <ChevronDown size={8} />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="text-center py-8 font-mono text-xs text-text-muted"
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            sorted.map(row => {
              const key = getRowKey(row)
              const selected = selectedRowKey === key

              return (
                <tr
                  key={key}
                  className={clsx(
                    'border-b border-border-muted transition-colors',
                    onRowClick && 'cursor-pointer',
                    selected
                      ? 'bg-[rgba(56,189,248,0.08)]'
                      : onRowClick ? 'hover:bg-bg-panel-hover' : '',
                    rowHeight
                  )}
                  onClick={() => onRowClick?.(row)}
                >
                  {columns.map(col => {
                    let cellValue: unknown
                    let renderedContent: React.ReactNode

                    if (typeof col.accessor === 'function') {
                      renderedContent = col.accessor(row)
                    } else {
                      cellValue = row[col.accessor as keyof T]
                      renderedContent = col.render
                        ? col.render(cellValue, row)
                        : String(cellValue ?? '—')
                    }

                    return (
                      <td
                        key={col.key}
                        className={clsx(
                          'font-mono text-[0.7rem] tabular-nums whitespace-nowrap text-text-primary',
                          cellPadding,
                          col.align === 'left' ? 'text-left' : col.align === 'center' ? 'text-center' : 'text-right',
                          col.className
                        )}
                      >
                        {renderedContent}
                      </td>
                    )
                  })}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}

export default DataTable

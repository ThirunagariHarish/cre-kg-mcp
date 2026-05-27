import React from 'react'
import clsx from 'clsx'

// ── Text Skeleton ──
interface TextSkeletonProps {
  lines?: number
  className?: string
  widths?: string[]
}

export function TextSkeleton({ lines = 1, className, widths }: TextSkeletonProps) {
  return (
    <div className={clsx('flex flex-col gap-1', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-3 skeleton rounded-sm"
          style={{ width: widths?.[i] ?? (i === lines - 1 && lines > 1 ? '70%' : '100%') }}
        />
      ))}
    </div>
  )
}

// ── Card Skeleton ──
interface CardSkeletonProps {
  rows?: number
  className?: string
}

export function CardSkeleton({ rows = 3, className }: CardSkeletonProps) {
  return (
    <div className={clsx('p-2.5 border border-border-subtle rounded-sm space-y-2', className)}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="w-8 h-3 skeleton rounded-sm" />
        <div className="flex-1 h-4 skeleton rounded-sm" />
        <div className="w-12 h-3 skeleton rounded-sm" />
      </div>
      {/* Body rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className={clsx('h-3 skeleton rounded-sm', i === rows - 1 ? 'w-4/5' : 'w-full')} />
      ))}
      {/* Footer */}
      <div className="flex gap-2 pt-1">
        <div className="w-16 h-5 skeleton rounded-sm" />
        <div className="w-16 h-5 skeleton rounded-sm" />
        <div className="flex-1 h-5 skeleton rounded-sm" />
      </div>
    </div>
  )
}

// ── Table Skeleton ──
interface TableSkeletonProps {
  rows?: number
  columns?: number
  className?: string
}

export function TableSkeleton({ rows = 10, columns = 6, className }: TableSkeletonProps) {
  return (
    <div className={clsx('overflow-hidden', className)}>
      {/* Header */}
      <div className="flex gap-1 px-2 py-1.5 border-b border-border-subtle">
        {Array.from({ length: columns }).map((_, i) => (
          <div
            key={i}
            className="h-2.5 skeleton rounded-sm flex-1"
            style={{ maxWidth: i === 0 ? '60px' : undefined }}
          />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, rowIdx) => (
        <div
          key={rowIdx}
          className="flex gap-1 px-2 py-1 border-b border-border-muted items-center"
        >
          {Array.from({ length: columns }).map((_, colIdx) => (
            <div
              key={colIdx}
              className="h-3 skeleton rounded-sm flex-1"
              style={{
                maxWidth: colIdx === 0 ? '60px' : undefined,
                opacity: 1 - (rowIdx * 0.06),
              }}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

// ── Chart Skeleton ──
interface ChartSkeletonProps {
  height?: number
  className?: string
}

export function ChartSkeleton({ height = 200, className }: ChartSkeletonProps) {
  return (
    <div
      className={clsx('relative overflow-hidden rounded-sm border border-border-subtle bg-bg-panel', className)}
      style={{ height }}
    >
      {/* Fake chart lines */}
      <div className="absolute inset-0 flex items-end px-4 pb-4 gap-1">
        {Array.from({ length: 30 }).map((_, i) => {
          const h = 20 + Math.sin(i * 0.4) * 30 + Math.random() * 40
          return (
            <div
              key={i}
              className="skeleton flex-1 rounded-sm opacity-40"
              style={{ height: `${h}%` }}
            />
          )
        })}
      </div>
      {/* Overlay shimmer */}
      <div className="absolute inset-0 skeleton" />
    </div>
  )
}

// ── Panel Skeleton (full panel) ──
export function PanelSkeleton({ className }: { className?: string }) {
  return (
    <div className={clsx('flex flex-col h-full border border-border-subtle', className)}>
      {/* Panel header */}
      <div className="flex items-center gap-2 px-2.5 py-1.5 border-b border-border-subtle">
        <div className="h-2.5 w-16 skeleton rounded-sm" />
        <div className="h-2.5 w-6 skeleton rounded-sm" />
        <div className="flex-1" />
        <div className="h-2.5 w-8 skeleton rounded-sm" />
      </div>
      {/* Content rows */}
      <div className="flex-1 p-1.5 space-y-0.5">
        <TableSkeleton rows={15} columns={4} />
      </div>
    </div>
  )
}

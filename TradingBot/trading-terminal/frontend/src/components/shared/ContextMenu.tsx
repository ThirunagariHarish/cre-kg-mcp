import React, { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { ChevronRight } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ContextMenuItem {
  id: string
  label: string
  icon?: React.ReactNode
  shortcut?: string
  disabled?: boolean
  destructive?: boolean
  onClick?: () => void
  submenu?: Omit<ContextMenuItem, 'submenu'>[]
}

export interface ContextMenuSeparator {
  id: string
  type: 'separator'
}

export type ContextMenuEntry = ContextMenuItem | ContextMenuSeparator

export interface ContextMenuPosition {
  x: number
  y: number
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export interface UseContextMenuState {
  open: boolean
  position: ContextMenuPosition
  items: ContextMenuEntry[]
  onOpen: (e: React.MouseEvent, items: ContextMenuEntry[]) => void
  onClose: () => void
}

export function useContextMenu(): UseContextMenuState {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<ContextMenuPosition>({ x: 0, y: 0 })
  const [items, setItems] = useState<ContextMenuEntry[]>([])

  const onOpen = useCallback((e: React.MouseEvent, menuItems: ContextMenuEntry[]) => {
    e.preventDefault()
    e.stopPropagation()
    setPosition({ x: e.clientX, y: e.clientY })
    setItems(menuItems)
    setOpen(true)
  }, [])

  const onClose = useCallback(() => {
    setOpen(false)
  }, [])

  return { open, position, items, onOpen, onClose }
}

// ── Standard menu item sets ───────────────────────────────────────────────────

export const WATCHLIST_CONTEXT_ITEMS = (
  symbol: string,
  handlers: {
    onAddToTicket?: () => void
    onSetAlert?: () => void
    onViewChart?: () => void
    onRemove?: () => void
  },
): ContextMenuEntry[] => [
  { id: 'add-ticket', label: 'Add to Trade Ticket', onClick: handlers.onAddToTicket },
  { id: 'set-alert', label: 'Set Alert', onClick: handlers.onSetAlert },
  { id: 'view-chart', label: `View Chart — ${symbol}`, onClick: handlers.onViewChart },
  { id: 'sep-1', type: 'separator' },
  { id: 'remove', label: 'Remove from Watchlist', destructive: true, onClick: handlers.onRemove },
]

export const POSITION_CONTEXT_ITEMS = (handlers: {
  onClose?: () => void
  onAddToSize?: () => void
  onReduceSize?: () => void
  onViewDetails?: () => void
}): ContextMenuEntry[] => [
  { id: 'close', label: 'Close Position', destructive: true, onClick: handlers.onClose },
  { id: 'sep-1', type: 'separator' },
  { id: 'add-size', label: 'Add to Size', onClick: handlers.onAddToSize },
  { id: 'reduce-size', label: 'Reduce Size', onClick: handlers.onReduceSize },
  { id: 'sep-2', type: 'separator' },
  { id: 'view-details', label: 'View Details', onClick: handlers.onViewDetails },
]

export const ORDER_CONTEXT_ITEMS = (
  orderId: string,
  handlers: {
    onCancel?: () => void
    onModify?: () => void
    onCopyId?: () => void
  },
): ContextMenuEntry[] => [
  { id: 'cancel', label: 'Cancel Order', destructive: true, onClick: handlers.onCancel },
  { id: 'modify', label: 'Modify Order', onClick: handlers.onModify },
  { id: 'sep-1', type: 'separator' },
  { id: 'copy-id', label: `Copy Order ID — ${orderId.slice(0, 8)}…`, onClick: handlers.onCopyId },
]

// ── Menu item renderer ────────────────────────────────────────────────────────

function MenuItemRow({
  item,
  onClose,
}: {
  item: ContextMenuItem
  onClose: () => void
}) {
  const [submenuOpen, setSubmenuOpen] = useState(false)
  const rowRef = useRef<HTMLDivElement>(null)
  const hasSubmenu = item.submenu && item.submenu.length > 0

  function handleClick() {
    if (item.disabled || hasSubmenu) return
    item.onClick?.()
    onClose()
  }

  return (
    <div
      ref={rowRef}
      role="menuitem"
      tabIndex={item.disabled ? -1 : 0}
      aria-disabled={item.disabled}
      aria-haspopup={hasSubmenu ? 'menu' : undefined}
      aria-expanded={hasSubmenu ? submenuOpen : undefined}
      className={clsx(
        'relative flex items-center gap-2 px-2.5 py-1.5 cursor-pointer select-none transition-colors',
        item.disabled
          ? 'opacity-40 cursor-not-allowed text-text-muted'
          : item.destructive
            ? 'text-negative hover:bg-negative-bg'
            : 'text-text-primary hover:bg-bg-panel-hover',
      )}
      onClick={handleClick}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') handleClick() }}
      onMouseEnter={() => hasSubmenu && setSubmenuOpen(true)}
      onMouseLeave={() => hasSubmenu && setSubmenuOpen(false)}
    >
      {item.icon && (
        <span className="flex-shrink-0 w-3 h-3 flex items-center justify-center">
          {item.icon}
        </span>
      )}
      <span className="flex-1 font-mono text-[0.65rem]">{item.label}</span>
      {item.shortcut && (
        <span className="font-mono text-[0.55rem] text-text-muted ml-2">{item.shortcut}</span>
      )}
      {hasSubmenu && (
        <ChevronRight size={10} className="text-text-muted flex-shrink-0" />
      )}

      {/* Submenu */}
      {hasSubmenu && submenuOpen && (
        <div className="absolute left-full top-0 z-[201] min-w-[160px] bg-bg-panel border border-border-subtle rounded-sm shadow-panel overflow-hidden">
          {item.submenu!.map(sub => (
            <div
              key={sub.id}
              role="menuitem"
              tabIndex={sub.disabled ? -1 : 0}
              aria-disabled={sub.disabled}
              className={clsx(
                'flex items-center gap-2 px-2.5 py-1.5 cursor-pointer select-none transition-colors',
                sub.disabled
                  ? 'opacity-40 cursor-not-allowed text-text-muted'
                  : sub.destructive
                    ? 'text-negative hover:bg-negative-bg'
                    : 'text-text-primary hover:bg-bg-panel-hover',
              )}
              onClick={(e) => {
                e.stopPropagation()
                if (!sub.disabled) {
                  sub.onClick?.()
                  onClose()
                }
              }}
              onKeyDown={e => {
                if ((e.key === 'Enter' || e.key === ' ') && !sub.disabled) {
                  sub.onClick?.()
                  onClose()
                }
              }}
            >
              {sub.icon && (
                <span className="flex-shrink-0 w-3 h-3 flex items-center justify-center">{sub.icon}</span>
              )}
              <span className="flex-1 font-mono text-[0.65rem]">{sub.label}</span>
              {sub.shortcut && (
                <span className="font-mono text-[0.55rem] text-text-muted">{sub.shortcut}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

interface ContextMenuProps {
  open: boolean
  position: ContextMenuPosition
  items: ContextMenuEntry[]
  onClose: () => void
}

function isSeparator(entry: ContextMenuEntry): entry is ContextMenuSeparator {
  return 'type' in entry && entry.type === 'separator'
}

function ContextMenuInner({ open, position, items, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClick, true)
    return () => document.removeEventListener('mousedown', handleClick, true)
  }, [open, onClose])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey, true)
    return () => document.removeEventListener('keydown', handleKey, true)
  }, [open, onClose])

  if (!open) return null

  // Adjust position to avoid viewport overflow
  const MENU_WIDTH = 200
  const MENU_HEIGHT = items.length * 32 + 8
  const x = Math.min(position.x, window.innerWidth - MENU_WIDTH - 8)
  const y = Math.min(position.y, window.innerHeight - MENU_HEIGHT - 8)

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      aria-orientation="vertical"
      className="fixed z-[200] min-w-[180px] bg-bg-panel border border-border-subtle rounded-sm shadow-panel overflow-hidden animate-fade-in"
      style={{ left: x, top: y }}
    >
      {items.map((entry, idx) => {
        if (isSeparator(entry)) {
          return <div key={entry.id ?? idx} className="h-px bg-border-subtle my-0.5" role="separator" />
        }
        return <MenuItemRow key={entry.id} item={entry} onClose={onClose} />
      })}
    </div>,
    document.body,
  )
}

export default ContextMenuInner

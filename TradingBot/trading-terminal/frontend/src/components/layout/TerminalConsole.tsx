import React, { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { format } from 'date-fns'
import { X, ChevronDown, Terminal, Trash2 } from 'lucide-react'
import type { SystemEvent } from '@/types/audit'
import { useTerminalStore } from '@/stores/terminalStore'

const COLOR_MAP: Record<string, string> = {
  cyan: 'text-accent-cyan',
  green: 'text-positive',
  red: 'text-negative',
  yellow: 'text-warning',
  white: 'text-text-primary',
  gray: 'text-text-muted',
}

const LEVEL_COLORS: Record<string, string> = {
  INFO: 'text-accent-cyan',
  SUCCESS: 'text-positive',
  WARNING: 'text-warning',
  ERROR: 'text-negative',
  COMMAND: 'text-text-primary',
}

const LEVEL_PREFIXES: Record<string, string> = {
  INFO: '[INFO ]',
  SUCCESS: '[  OK ]',
  WARNING: '[ WARN]',
  ERROR: '[ERROR]',
  COMMAND: '[  >> ]',
}

interface ConsoleLineProps {
  event: SystemEvent
}

function ConsoleLine({ event }: ConsoleLineProps) {
  const timeStr = format(event.timestamp, 'HH:mm:ss.SSS')
  const colorClass = event.color
    ? COLOR_MAP[event.color]
    : LEVEL_COLORS[event.type] ?? 'text-text-primary'
  const prefix = LEVEL_PREFIXES[event.type] ?? '[     ]'

  return (
    <div className="flex items-start gap-2 hover:bg-bg-panel transition-colors py-px px-2.5 group">
      {/* Timestamp */}
      <span className="font-mono text-[0.6rem] text-text-muted flex-shrink-0 tabular-nums">
        {timeStr}
      </span>
      {/* Level prefix */}
      <span className={clsx('font-mono text-[0.6rem] flex-shrink-0', colorClass)}>
        {prefix}
      </span>
      {/* Message */}
      <span className={clsx('font-mono text-[0.65rem] flex-1 break-all', colorClass)}>
        {event.source && (
          <span className="text-text-muted">[{event.source}] </span>
        )}
        {event.message}
      </span>
    </div>
  )
}

interface TerminalConsoleProps {
  onClose?: () => void
}

export default function TerminalConsole({ onClose }: TerminalConsoleProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [height, setHeight] = useState(160)
  const [isDragging, setIsDragging] = useState(false)
  const [inputValue, setInputValue] = useState('')

  const events = useTerminalStore(s => s.consoleEvents)
  const addConsoleEvent = useTerminalStore(s => s.addConsoleEvent)
  const clearConsole = useTerminalStore(s => s.clearConsole)

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events, autoScroll])

  // Detect manual scroll
  const handleScroll = () => {
    if (!scrollRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    setAutoScroll(scrollTop + clientHeight >= scrollHeight - 10)
  }

  // Resize handle (drag top edge)
  const handleResizeMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    setIsDragging(true)
    const startY = e.clientY
    const startHeight = height

    const onMove = (ev: MouseEvent) => {
      const newH = Math.min(400, Math.max(80, startHeight - (ev.clientY - startY)))
      setHeight(newH)
    }
    const onUp = () => {
      setIsDragging(false)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  const handleCommand = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && inputValue.trim()) {
      addConsoleEvent({
        id: crypto.randomUUID(),
        type: 'COMMAND',
        message: inputValue.trim(),
        timestamp: Date.now(),
        source: 'USER',
      })
      setInputValue('')
    }
  }

  return (
    <div className="flex flex-col bg-bg-root" style={{ height }}>
      {/* Resize handle */}
      <div
        className={clsx(
          'h-1 w-full cursor-row-resize flex-shrink-0',
          'hover:bg-accent-cyan transition-colors',
          isDragging ? 'bg-accent-cyan' : 'bg-border-subtle'
        )}
        onMouseDown={handleResizeMouseDown}
      />

      {/* Console Header */}
      <div className="panel-header">
        <Terminal size={10} className="text-accent-cyan flex-shrink-0" />
        <span className="flex-1">◈ Console</span>

        {/* Event count */}
        <span className="font-mono text-[0.55rem] text-text-muted">
          {events.length} events
        </span>

        {/* Auto-scroll indicator */}
        {!autoScroll && (
          <button
            onClick={() => {
              setAutoScroll(true)
              if (scrollRef.current) {
                scrollRef.current.scrollTop = scrollRef.current.scrollHeight
              }
            }}
            className="font-mono text-[0.55rem] text-accent-cyan hover:underline px-1"
          >
            ↓ scroll
          </button>
        )}

        {/* Clear */}
        <button
          onClick={clearConsole}
          title="Clear console"
          className="p-0.5 text-text-muted hover:text-negative hover:bg-bg-panel-raised rounded-sm transition-colors"
        >
          <Trash2 size={9} />
        </button>

        {/* Collapse */}
        {onClose && (
          <button
            onClick={onClose}
            title="Collapse console (Ctrl+`)"
            className="p-0.5 text-text-muted hover:text-text-primary hover:bg-bg-panel-raised rounded-sm transition-colors"
          >
            <ChevronDown size={10} />
          </button>
        )}
      </div>

      {/* Console Output */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto py-1 min-h-0"
      >
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <span className="font-mono text-[0.6rem] text-text-muted">
              — terminal ready —
            </span>
          </div>
        ) : (
          events.map(event => (
            <ConsoleLine key={event.id} event={event} />
          ))
        )}

        {/* Blinking cursor at end */}
        <div className="flex items-center gap-2 px-2.5 py-px">
          <span className="font-mono text-[0.65rem] text-accent-cyan cursor-blink" />
        </div>
      </div>

      {/* Command Input */}
      <div className="flex items-center gap-2 px-2.5 py-1.5 border-t border-border-subtle flex-shrink-0">
        <span className="font-mono text-[0.65rem] text-accent-cyan flex-shrink-0">{'>'}</span>
        <input
          type="text"
          value={inputValue}
          onChange={e => setInputValue(e.target.value)}
          onKeyDown={handleCommand}
          placeholder="Enter command..."
          className={clsx(
            'flex-1 bg-transparent border-none outline-none',
            'font-mono text-[0.65rem] text-text-primary placeholder:text-text-muted'
          )}
        />
      </div>
    </div>
  )
}

import React, { useState, useCallback } from 'react'
import clsx from 'clsx'
import GlobalCommandBar from './GlobalCommandBar'
import TerminalConsole from './TerminalConsole'
import TickerTape from './TickerTape'

interface TerminalShellProps {
  leftPanel: React.ReactNode
  mainWorkspace: React.ReactNode
  rightPanel: React.ReactNode
}

type FocusedPanel = 'left' | 'main' | 'right' | 'console' | null

export default function TerminalShell({
  leftPanel,
  mainWorkspace,
  rightPanel,
}: TerminalShellProps) {
  const [focusedPanel, setFocusedPanel] = useState<FocusedPanel>('main')
  const [consoleOpen, setConsoleOpen] = useState(true)
  const [leftWidth, setLeftWidth] = useState(260)
  const [rightWidth, setRightWidth] = useState(320)
  const [isDraggingLeft, setIsDraggingLeft] = useState(false)
  const [isDraggingRight, setIsDraggingRight] = useState(false)

  const handleLeftMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsDraggingLeft(true)
    const startX = e.clientX
    const startWidth = leftWidth
    const onMouseMove = (ev: MouseEvent) => {
      setLeftWidth(Math.min(400, Math.max(180, startWidth + ev.clientX - startX)))
    }
    const onMouseUp = () => {
      setIsDraggingLeft(false)
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [leftWidth])

  const handleRightMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsDraggingRight(true)
    const startX = e.clientX
    const startWidth = rightWidth
    const onMouseMove = (ev: MouseEvent) => {
      setRightWidth(Math.min(460, Math.max(240, startWidth - (ev.clientX - startX))))
    }
    const onMouseUp = () => {
      setIsDraggingRight(false)
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [rightWidth])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.ctrlKey || e.metaKey) {
      if (e.key === '1') setFocusedPanel('left')
      else if (e.key === '2') setFocusedPanel('main')
      else if (e.key === '3') setFocusedPanel('right')
      else if (e.key === '`') setConsoleOpen(v => !v)
    }
  }, [])

  return (
    <div
      className="flex flex-col h-full w-full overflow-hidden bg-bg-root select-none"
      onKeyDown={handleKeyDown}
      tabIndex={-1}
    >
      {/* ── Top Command Bar ── */}
      <GlobalCommandBar />

      {/* ── Ticker Tape ── */}
      <TickerTape />

      {/* ── Main 3-Column Layout ── */}
      <div className="flex flex-1 overflow-hidden min-h-0">

        {/* Left Panel */}
        <div
          className={clsx(
            'flex flex-col overflow-hidden border-r border-border-subtle flex-shrink-0 bg-bg-panel',
            focusedPanel === 'left' && 'shadow-[inset_2px_0_0_#ff6600]'
          )}
          style={{ width: leftWidth }}
          onClick={() => setFocusedPanel('left')}
        >
          {leftPanel}
        </div>

        {/* Left Resize Handle */}
        <div
          className={clsx('resize-handle', isDraggingLeft && 'dragging')}
          onMouseDown={handleLeftMouseDown}
        />

        {/* Main Workspace */}
        <div
          className={clsx(
            'flex flex-col flex-1 overflow-hidden min-w-0 border-r border-border-subtle bg-bg-panel',
            focusedPanel === 'main' && 'shadow-[inset_0_2px_0_#ff6600]'
          )}
          onClick={() => setFocusedPanel('main')}
        >
          {mainWorkspace}
        </div>

        {/* Right Resize Handle */}
        <div
          className={clsx('resize-handle', isDraggingRight && 'dragging')}
          onMouseDown={handleRightMouseDown}
        />

        {/* Right Panel */}
        <div
          className={clsx(
            'flex flex-col overflow-hidden flex-shrink-0 bg-bg-panel',
            focusedPanel === 'right' && 'shadow-[-2px_0_0_#ff6600]'
          )}
          style={{ width: rightWidth }}
          onClick={() => setFocusedPanel('right')}
        >
          {rightPanel}
        </div>
      </div>

      {/* ── Bottom Console ── */}
      {consoleOpen ? (
        <div
          className={clsx(
            'flex-shrink-0 border-t-2',
            focusedPanel === 'console' ? 'border-t-accent-cyan' : 'border-t-border-subtle'
          )}
          onClick={() => setFocusedPanel('console')}
        >
          <TerminalConsole onClose={() => setConsoleOpen(false)} />
        </div>
      ) : (
        <div className="flex-shrink-0 border-t border-border-subtle">
          <button
            className="w-full h-5 flex items-center justify-center gap-2 text-[0.6rem] font-mono text-text-muted hover:text-accent-cyan hover:bg-bg-panel-raised transition-colors"
            onClick={() => setConsoleOpen(true)}
          >
            <span>▲ CONSOLE</span>
            <span className="text-text-dim">Ctrl+`</span>
          </button>
        </div>
      )}
    </div>
  )
}

import React, { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { format } from 'date-fns'
import { Terminal, Bell, Settings, Search } from 'lucide-react'
import { useTerminalStore } from '@/stores/terminalStore'
import MarketRegimeBadge from '@/components/intelligence/MarketRegimeBadge'
import PaperLiveToggle from '@/components/shared/PaperLiveToggle'
import AlertCreator from '@/components/shared/AlertCreator'
import RiskPolicyEditor from '@/components/risk/RiskPolicyEditor'
import { useIndices } from '@/hooks/useIndices'

interface IndexData {
  name: string
  price: number
  change: number
  changePct: number
}

const HEALTH_INDICATORS = [
  { name: 'API', status: 'online' as const },
  { name: 'WS',  status: 'online' as const },
  { name: 'MKT', status: 'online' as const },
  { name: 'RISK',status: 'warning' as const },
]

function IndexTile({ idx }: { idx: IndexData }) {
  const up = idx.changePct >= 0
  return (
    <div className="flex items-center gap-2 px-3 h-full border-r border-border-subtle flex-shrink-0">
      <span className="font-mono text-[0.6rem] text-text-muted tracking-widest">{idx.name}</span>
      <span className="font-mono text-[0.72rem] text-text-primary tabular-nums font-medium">
        {idx.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </span>
      <span className={clsx(
        'font-mono text-[0.62rem] tabular-nums',
        up ? 'text-positive' : 'text-negative'
      )}>
        {up ? '+' : ''}{idx.changePct.toFixed(2)}%
      </span>
    </div>
  )
}


export default function GlobalCommandBar() {
  const [now, setNow] = useState(new Date())
  const [alertPanelOpen, setAlertPanelOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { data: indicesData } = useIndices()

  const indices = [
    { name: 'SPX', key: 'SPY' },
    { name: 'NDX', key: 'QQQ' },
    { name: 'DJI', key: 'DIA' },
    { name: 'VIX', key: '^VIX' },
  ]
  const alertPanelRef = useRef<HTMLDivElement>(null)
  const mode = useTerminalStore(s => s.mode)
  const setMode = useTerminalStore(s => s.setMode)
  const alertCount = useTerminalStore(s => s.alerts.length)
  const setCommandPaletteOpen = useTerminalStore(s => s.setCommandPaletteOpen)

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setCommandPaletteOpen(true)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setCommandPaletteOpen])

  useEffect(() => {
    if (!alertPanelOpen) return
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setAlertPanelOpen(false)
    }
    const handleClickOutside = (e: MouseEvent) => {
      if (alertPanelRef.current && !alertPanelRef.current.contains(e.target as Node)) {
        setAlertPanelOpen(false)
      }
    }
    window.addEventListener('keydown', handleEscape)
    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      window.removeEventListener('keydown', handleEscape)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [alertPanelOpen])

  useEffect(() => {
    if (!settingsOpen) return
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSettingsOpen(false)
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [settingsOpen])

  return (
    <>
    <div className="flex items-center h-9 bg-bg-panel border-b border-border-subtle flex-shrink-0 overflow-hidden select-none">

      {/* Logo */}
      <div className="flex items-center gap-2 px-3 h-full border-r border-border-subtle flex-shrink-0">
        <Terminal size={11} className="text-accent-cyan" />
        <span className="font-mono text-[0.7rem] font-semibold text-accent-cyan tracking-[0.2em]">
          TERM
        </span>
      </div>

      {/* Mode Toggle */}
      <div className="flex items-center px-1.5 h-full border-r border-border-subtle flex-shrink-0">
        <PaperLiveToggle mode={mode} onModeChange={async (m) => setMode(m)} />
      </div>

      {/* Market Indices */}
      {indices.map(({ name, key }) => {
        const q = indicesData?.[key]
        if (!q) return null
        return (
          <IndexTile
            key={name}
            idx={{
              name,
              price: q.last ?? 0,
              change: q.change ?? 0,
              changePct: q.changePercent ?? 0,
            }}
          />
        )
      })}

      {/* Search */}
      <button
        className="flex items-center gap-2 flex-1 h-full px-4 hover:bg-bg-panel-raised transition-colors focus-visible:outline-none border-r border-border-subtle min-w-0"
        onClick={() => setCommandPaletteOpen(true)}
      >
        <Search size={10} className="text-text-muted flex-shrink-0" />
        <span className="font-mono text-[0.65rem] text-text-muted truncate">
          Search symbols, commands...
        </span>
        <span className="font-mono text-[0.55rem] text-text-dim flex-shrink-0 ml-auto">⌘K</span>
      </button>

      {/* Market Regime Badge */}
      <div className="flex items-center px-2 h-full border-r border-border-subtle flex-shrink-0">
        <MarketRegimeBadge variant="badge" />
      </div>

      {/* Market Status */}
      <div className="flex items-center gap-1.5 px-3 h-full border-r border-border-subtle flex-shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-positive flex-shrink-0" />
        <span className="font-mono text-[0.6rem] text-positive tracking-wider">OPEN</span>
      </div>

      {/* Health Indicators */}
      <div className="flex items-center gap-2.5 px-3 h-full border-r border-border-subtle flex-shrink-0">
        {HEALTH_INDICATORS.map(h => {
          const color = h.status === 'online' ? 'bg-positive' : h.status === 'warning' ? 'bg-warning' : 'bg-negative'
          return (
            <div key={h.name} className="flex items-center gap-1" title={`${h.name}: ${h.status}`}>
              <span className={clsx('w-1.5 h-1.5 rounded-full flex-shrink-0', color)} />
              <span className="font-mono text-[0.55rem] text-text-muted hidden xl:block">{h.name}</span>
            </div>
          )
        })}
      </div>

      {/* Clock */}
      <div className="flex items-center gap-1 px-3 h-full border-r border-border-subtle flex-shrink-0">
        <span className="font-mono text-[0.68rem] text-text-secondary tabular-nums">
          {format(now, 'HH:mm:ss')}
        </span>
        <span className="font-mono text-[0.55rem] text-text-muted">ET</span>
      </div>

      {/* Alert Bell */}
      <div className="relative flex-shrink-0" ref={alertPanelRef}>
        <button
          className={clsx(
            'flex items-center gap-1 px-3 h-full border-r border-border-subtle',
            'hover:bg-bg-panel-raised transition-colors focus-visible:outline-none',
            alertCount > 0 ? 'text-warning' : 'text-text-muted'
          )}
          title={`${alertCount} alerts`}
          onClick={() => setAlertPanelOpen(prev => !prev)}
        >
          <Bell size={12} />
          {alertCount > 0 && (
            <span className="font-mono text-[0.6rem] text-warning">{alertCount > 99 ? '99+' : alertCount}</span>
          )}
        </button>
        {alertPanelOpen && (
          <div className="absolute right-0 top-full w-96 bg-bg-panel border border-border-subtle z-50 shadow-xl overflow-y-auto max-h-[80vh]">
            <AlertCreator />
          </div>
        )}
      </div>

      {/* Settings */}
      <button
        className="flex items-center px-3 h-full text-text-muted hover:text-text-primary hover:bg-bg-panel-raised transition-colors focus-visible:outline-none"
        title="Settings"
        onClick={() => setSettingsOpen(true)}
      >
        <Settings size={12} />
      </button>
    </div>

    {/* Settings Modal */}
    {settingsOpen && (
      <div
        className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center"
        role="dialog"
        aria-modal="true"
        aria-label="Risk Policy Settings"
        onClick={(e) => { if (e.target === e.currentTarget) setSettingsOpen(false) }}
      >
        <div className="w-[600px] max-h-[80vh] overflow-y-auto bg-bg-panel border border-border-subtle">
          {/* Modal header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-border-subtle flex-shrink-0">
            <span className="font-mono text-[0.7rem] text-accent-cyan tracking-wider">◈ Risk Policy</span>
            <button
              onClick={() => setSettingsOpen(false)}
              className="font-mono text-[0.8rem] text-text-muted hover:text-text-primary transition-colors focus-visible:outline-none"
              aria-label="Close settings"
            >
              ✕
            </button>
          </div>
          <RiskPolicyEditor />
        </div>
      </div>
    )}
    </>
  )
}

import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'
import type { SystemEvent } from '@/types/audit'

export type TradingMode = 'PAPER' | 'LIVE'
export type ActivePanel = 'left' | 'main' | 'right' | 'console' | null
export type WorkspaceTab =
  | 'POSITIONS'
  | 'AGENTS'
  | 'ORDERS'
  | 'SIGNALS'
  | 'CHART'
  | 'ANALYTICS'
  | 'INTELLIGENCE'
  | 'BACKTEST'

export type AlertType =
  | 'SIGNAL_HIGH_CONFIDENCE'
  | 'RISK_BREACH'
  | 'FILL_COMPLETE'
  | 'ERROR'
  | 'INFO'
  | 'WARNING'

export interface Alert {
  id: string
  type: AlertType
  message: string
  symbol?: string
  timestamp: number
}

/** Persisted slice — written to localStorage under 'term-terminal-store'. */
interface PersistedState {
  workspaceTab: WorkspaceTab
  sidebarCollapsed: boolean
  commandHistory: string[]
}

/** Ephemeral slice — not persisted (alerts, console, palette). */
interface EphemeralState {
  mode: TradingMode
  setMode: (mode: TradingMode) => void

  activePanel: ActivePanel
  setActivePanel: (panel: ActivePanel) => void

  commandPaletteOpen: boolean
  setCommandPaletteOpen: (open: boolean) => void

  alerts: Alert[]
  addAlert: (alert: Omit<Alert, 'id' | 'timestamp'>) => void
  dismissAlert: (id: string) => void
  clearAlerts: () => void

  consoleEvents: SystemEvent[]
  addConsoleEvent: (event: SystemEvent) => void
  clearConsole: () => void
}

interface TerminalState extends PersistedState, EphemeralState {
  addCommandHistory: (cmd: string) => void
  setWorkspaceTab: (tab: WorkspaceTab) => void
  setSidebarCollapsed: (v: boolean) => void
}

const MAX_CONSOLE_EVENTS = 500
const MAX_COMMAND_HISTORY = 50
const MAX_ALERTS = 20

export const useTerminalStore = create<TerminalState>()(
  devtools(
    persist(
      (set, _get) => ({
        // ---------------------------------------------------------------- Persisted
        workspaceTab: 'POSITIONS',
        setWorkspaceTab: (tab) => set({ workspaceTab: tab }),

        sidebarCollapsed: false,
        setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),

        commandHistory: [],
        addCommandHistory: (cmd) =>
          set(state => ({
            commandHistory: [
              cmd,
              ...state.commandHistory.filter(c => c !== cmd),
            ].slice(0, MAX_COMMAND_HISTORY),
          })),

        // --------------------------------------------------------------- Ephemeral
        mode: 'PAPER',
        setMode: (mode) => set({ mode }),

        activePanel: 'main',
        setActivePanel: (panel) => set({ activePanel: panel }),

        commandPaletteOpen: false,
        setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),

        alerts: [],
        addAlert: (alert) =>
          set(state => ({
            alerts: [
              { ...alert, id: crypto.randomUUID(), timestamp: Date.now() },
              ...state.alerts,
            ].slice(0, MAX_ALERTS),
          })),
        dismissAlert: (id) =>
          set(state => ({
            alerts: state.alerts.filter(a => a.id !== id),
          })),
        clearAlerts: () => set({ alerts: [] }),

        consoleEvents: [
          {
            id: '1',
            type: 'INFO',
            message: 'TERM v1.0.0 — Trading Terminal initialized',
            timestamp: Date.now(),
            source: 'SYSTEM',
            color: 'cyan',
          },
          {
            id: '2',
            type: 'INFO',
            message: 'Mode: PAPER — Risk engine: ACTIVE',
            timestamp: Date.now(),
            source: 'SYSTEM',
            color: 'gray',
          },
        ],
        addConsoleEvent: (event) =>
          set(state => ({
            consoleEvents: [...state.consoleEvents, event].slice(
              -MAX_CONSOLE_EVENTS
            ),
          })),
        clearConsole: () => set({ consoleEvents: [] }),
      }),
      {
        name: 'term-terminal-store',
        // Only persist the three fields; everything else is ephemeral.
        partialize: (state): PersistedState => ({
          workspaceTab: state.workspaceTab,
          sidebarCollapsed: state.sidebarCollapsed,
          commandHistory: state.commandHistory,
        }),
      }
    ),
    { name: 'terminal-store' }
  )
)

import { describe, it, expect, beforeEach } from 'vitest'
import { useTerminalStore } from './terminalStore'

// Reset only the data fields, not the action functions.
// Using replace:true would wipe action functions from the store; merge instead.
function resetStore() {
  useTerminalStore.setState({
    workspaceTab: 'POSITIONS',
    sidebarCollapsed: false,
    commandHistory: [],
    mode: 'PAPER',
    activePanel: 'main',
    commandPaletteOpen: false,
    alerts: [],
    consoleEvents: [],
  })
}

describe('terminalStore — initial state', () => {
  beforeEach(resetStore)

  it('starts on POSITIONS workspace tab', () => {
    expect(useTerminalStore.getState().workspaceTab).toBe('POSITIONS')
  })

  it('starts in PAPER mode', () => {
    expect(useTerminalStore.getState().mode).toBe('PAPER')
  })

  it('starts with no alerts', () => {
    expect(useTerminalStore.getState().alerts).toHaveLength(0)
  })

  it('starts with empty command history', () => {
    expect(useTerminalStore.getState().commandHistory).toHaveLength(0)
  })
})

describe('terminalStore — setWorkspaceTab', () => {
  beforeEach(resetStore)

  it('switches to AGENTS tab', () => {
    useTerminalStore.getState().setWorkspaceTab('AGENTS')
    expect(useTerminalStore.getState().workspaceTab).toBe('AGENTS')
  })

  it('switches through every tab', () => {
    const tabs = [
      'POSITIONS',
      'AGENTS',
      'ORDERS',
      'SIGNALS',
      'CHART',
      'ANALYTICS',
      'INTELLIGENCE',
      'BACKTEST',
    ] as const

    for (const tab of tabs) {
      useTerminalStore.getState().setWorkspaceTab(tab)
      expect(useTerminalStore.getState().workspaceTab).toBe(tab)
    }
  })
})

describe('terminalStore — setMode', () => {
  beforeEach(resetStore)

  it('switches from PAPER to LIVE', () => {
    useTerminalStore.getState().setMode('LIVE')
    expect(useTerminalStore.getState().mode).toBe('LIVE')
  })

  it('switches back from LIVE to PAPER', () => {
    useTerminalStore.getState().setMode('LIVE')
    useTerminalStore.getState().setMode('PAPER')
    expect(useTerminalStore.getState().mode).toBe('PAPER')
  })
})

describe('terminalStore — addAlert', () => {
  beforeEach(resetStore)

  it('adds an alert with generated id and timestamp', () => {
    useTerminalStore.getState().addAlert({
      type: 'INFO',
      message: 'Test alert',
    })
    const alerts = useTerminalStore.getState().alerts
    expect(alerts).toHaveLength(1)
    expect(alerts[0].type).toBe('INFO')
    expect(alerts[0].message).toBe('Test alert')
    expect(typeof alerts[0].id).toBe('string')
    expect(alerts[0].id.length).toBeGreaterThan(0)
    expect(typeof alerts[0].timestamp).toBe('number')
  })

  it('prepends new alerts so the latest is first', () => {
    useTerminalStore.getState().addAlert({ type: 'INFO', message: 'first' })
    useTerminalStore.getState().addAlert({ type: 'WARNING', message: 'second' })
    const alerts = useTerminalStore.getState().alerts
    expect(alerts[0].message).toBe('second')
    expect(alerts[1].message).toBe('first')
  })

  it('adds an alert with optional symbol', () => {
    useTerminalStore.getState().addAlert({
      type: 'SIGNAL_HIGH_CONFIDENCE',
      message: 'BUY signal',
      symbol: 'AAPL',
    })
    expect(useTerminalStore.getState().alerts[0].symbol).toBe('AAPL')
  })

  it('caps alerts at 20', () => {
    for (let i = 0; i < 25; i++) {
      useTerminalStore.getState().addAlert({ type: 'INFO', message: `alert ${i}` })
    }
    expect(useTerminalStore.getState().alerts).toHaveLength(20)
  })
})

describe('terminalStore — dismissAlert', () => {
  beforeEach(resetStore)

  it('removes the alert with the matching id', () => {
    useTerminalStore.getState().addAlert({ type: 'INFO', message: 'to-be-dismissed' })
    const id = useTerminalStore.getState().alerts[0].id
    useTerminalStore.getState().dismissAlert(id)
    expect(useTerminalStore.getState().alerts).toHaveLength(0)
  })

  it('leaves other alerts intact when dismissing one', () => {
    useTerminalStore.getState().addAlert({ type: 'INFO', message: 'keep' })
    useTerminalStore.getState().addAlert({ type: 'ERROR', message: 'remove' })
    // latest is first
    const removeId = useTerminalStore.getState().alerts[0].id
    useTerminalStore.getState().dismissAlert(removeId)
    const remaining = useTerminalStore.getState().alerts
    expect(remaining).toHaveLength(1)
    expect(remaining[0].message).toBe('keep')
  })

  it('is a no-op for an unknown id', () => {
    useTerminalStore.getState().addAlert({ type: 'INFO', message: 'safe' })
    useTerminalStore.getState().dismissAlert('non-existent-id')
    expect(useTerminalStore.getState().alerts).toHaveLength(1)
  })
})

describe('terminalStore — addCommandHistory', () => {
  beforeEach(resetStore)

  it('adds a command at the front', () => {
    useTerminalStore.getState().addCommandHistory('GO AAPL')
    expect(useTerminalStore.getState().commandHistory[0]).toBe('GO AAPL')
  })

  it('deduplicates — keeps only the latest occurrence', () => {
    useTerminalStore.getState().addCommandHistory('GO AAPL')
    useTerminalStore.getState().addCommandHistory('GO NVDA')
    useTerminalStore.getState().addCommandHistory('GO AAPL')
    const history = useTerminalStore.getState().commandHistory
    // 'GO AAPL' should appear only once, at the front
    expect(history[0]).toBe('GO AAPL')
    expect(history.filter(c => c === 'GO AAPL')).toHaveLength(1)
  })

  it('caps history at 50 entries', () => {
    for (let i = 0; i < 55; i++) {
      useTerminalStore.getState().addCommandHistory(`CMD ${i}`)
    }
    expect(useTerminalStore.getState().commandHistory).toHaveLength(50)
  })
})

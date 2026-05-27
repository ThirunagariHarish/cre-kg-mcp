import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import type { Signal } from '@/types/signals'

// ---------------------------------------------------------------------------
// Mock the API client BEFORE importing the hook.
// vi.mock is hoisted by Vitest so this mock is in place when the module loads.
// ---------------------------------------------------------------------------
vi.mock('@/lib/api/client', () => ({
  apiGet: vi.fn(),
}))

import { useLiveSignals } from './useLiveSignals'
import { apiGet } from '@/lib/api/client'

const mockedApiGet = vi.mocked(apiGet)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function makeSignal(id: string): Signal {
  return {
    id,
    source: 'AI',
    rawMessage: `signal ${id}`,
    ticker: 'AAPL',
    direction: 'BUY',
    status: 'PENDING',
    receivedAt: Date.now(),
  }
}

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        retryDelay: 0,
        refetchInterval: false,
      },
    },
  })
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client }, children)
  return { wrapper, client }
}

// ---------------------------------------------------------------------------
// Tests — when the hook is enabled (VITE_MOCK_DATA defaults to undefined/false)
// ---------------------------------------------------------------------------
describe('useLiveSignals — enabled (VITE_MOCK_DATA not "true")', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_MOCK_DATA', 'false')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetAllMocks()
  })

  it('returns an empty array while the query has not resolved', () => {
    // Promise that never resolves = perpetual loading state
    mockedApiGet.mockReturnValue(new Promise(() => {}))
    const { wrapper } = makeWrapper()
    const { result } = renderHook(() => useLiveSignals(), { wrapper })
    // placeholderData is [] so signals is always defined
    expect(result.current.signals).toEqual([])
  })

  it('returns signals array when the API responds with a plain array', async () => {
    const signals = [makeSignal('s1'), makeSignal('s2')]
    mockedApiGet.mockResolvedValueOnce(signals)
    const { wrapper } = makeWrapper()
    const { result } = renderHook(() => useLiveSignals(), { wrapper })

    await waitFor(() => expect(result.current.signals).toHaveLength(2))
    expect(result.current.signals[0].id).toBe('s1')
    expect(result.current.error).toBeNull()
  })

  it('returns signals when API responds with { signals: [...] }', async () => {
    const signals = [makeSignal('s3')]
    mockedApiGet.mockResolvedValueOnce({ signals })
    const { wrapper } = makeWrapper()
    const { result } = renderHook(() => useLiveSignals(), { wrapper })

    await waitFor(() => expect(result.current.signals).toHaveLength(1))
    expect(result.current.signals[0].id).toBe('s3')
  })

  it('returns signals when API responds with { items: [...] }', async () => {
    const items = [makeSignal('s4')]
    mockedApiGet.mockResolvedValueOnce({ items })
    const { wrapper } = makeWrapper()
    const { result } = renderHook(() => useLiveSignals(), { wrapper })

    await waitFor(() => expect(result.current.signals).toHaveLength(1))
    expect(result.current.signals[0].id).toBe('s4')
  })

  it('returns signals when API responds with { data: [...] }', async () => {
    const data = [makeSignal('s5')]
    mockedApiGet.mockResolvedValueOnce({ data })
    const { wrapper } = makeWrapper()
    const { result } = renderHook(() => useLiveSignals(), { wrapper })

    await waitFor(() => expect(result.current.signals).toHaveLength(1))
    expect(result.current.signals[0].id).toBe('s5')
  })

  it('returns empty array and exposes error when the API throws', async () => {
    mockedApiGet.mockRejectedValue(new Error('Network error'))
    const { wrapper } = makeWrapper()
    const { result } = renderHook(() => useLiveSignals(), { wrapper })

    // Wait until React Query settles into error state
    await waitFor(() => expect(result.current.error).not.toBeNull(), { timeout: 4000 })
    // placeholderData keeps signals as [] even on error
    expect(result.current.signals).toEqual([])
    expect(result.current.error).toBeInstanceOf(Error)
  })
})

// ---------------------------------------------------------------------------
// Tests — disabled via VITE_MOCK_DATA
// The hook reads import.meta.env.VITE_MOCK_DATA at call time (inside useQuery).
// In Vitest, vi.stubEnv patches import.meta.env before the reactive expression
// inside useQuery runs, so enabled becomes false.
// ---------------------------------------------------------------------------
describe('useLiveSignals — disabled when VITE_MOCK_DATA=true', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_MOCK_DATA', 'true')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.clearAllMocks()
  })

  it('returns an empty signals array without calling apiGet', async () => {
    const { wrapper } = makeWrapper()
    const { result } = renderHook(() => useLiveSignals(), { wrapper })

    // Let the event loop settle; if the query were enabled apiGet would be called
    await new Promise(r => setTimeout(r, 30))

    expect(result.current.signals).toEqual([])
    expect(result.current.error).toBeNull()
  })
})

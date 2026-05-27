import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE } from '@/lib/api/client'

const API_TOKEN = import.meta.env.VITE_API_TOKEN ?? ''
const RECONNECT_DELAY_MS = 3_000
const MAX_RETRIES = 5

export interface UseSSEOptions<T> {
  /** When false the connection is not opened. Defaults to true. */
  enabled?: boolean
  /** Called for every parsed SSE data message. */
  onMessage?: (data: T) => void
}

export interface UseSSEReturn<T> {
  connected: boolean
  lastEvent: T | null
  error: Error | null
}

/**
 * Subscribes to a Server-Sent Events stream.
 *
 * The auth token is appended as `?token=<VITE_API_TOKEN>` because
 * the browser EventSource API does not support custom headers.
 *
 * Auto-reconnects on error with a 3 s backoff, up to MAX_RETRIES times.
 * Cleans up the EventSource on unmount or when `enabled` becomes false.
 */
export function useSSE<T = unknown>(
  url: string,
  options: UseSSEOptions<T> = {}
): UseSSEReturn<T> {
  const { enabled = true, onMessage } = options

  const [connected, setConnected] = useState(false)
  const [lastEvent, setLastEvent] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)

  const esRef = useRef<EventSource | null>(null)
  const retryCountRef = useRef(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const close = useCallback(() => {
    if (retryTimerRef.current !== null) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    setConnected(false)
  }, [])

  const connect = useCallback(() => {
    close()

    const separator = url.includes('?') ? '&' : '?'
    const fullUrl = `${API_BASE}${url}${API_TOKEN ? `${separator}token=${encodeURIComponent(API_TOKEN)}` : ''}`

    const es = new EventSource(fullUrl)
    esRef.current = es

    es.onopen = () => {
      retryCountRef.current = 0
      setConnected(true)
      setError(null)
    }

    es.onmessage = (evt: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(evt.data) as T
        setLastEvent(parsed)
        onMessageRef.current?.(parsed)
      } catch {
        // Non-JSON messages (heartbeat pings, etc.) are silently ignored.
      }
    }

    es.onerror = () => {
      es.close()
      esRef.current = null
      setConnected(false)

      if (retryCountRef.current >= MAX_RETRIES) {
        setError(new Error(`[SSE] Max retries (${MAX_RETRIES}) reached: ${url}`))
        return
      }

      retryCountRef.current += 1
      retryTimerRef.current = setTimeout(() => {
        connect()
      }, RECONNECT_DELAY_MS)
    }
  }, [url, close])

  useEffect(() => {
    if (!enabled) {
      close()
      return
    }

    retryCountRef.current = 0
    connect()

    return close
  }, [enabled, connect, close])

  return { connected, lastEvent, error }
}

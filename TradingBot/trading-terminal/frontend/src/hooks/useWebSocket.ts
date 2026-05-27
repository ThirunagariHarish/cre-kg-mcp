import { useEffect, useRef, useState, useCallback } from 'react'
import { useAuthStore } from '@/stores/authStore'

export interface WsMessage {
  type: string
  data?: unknown
  ts?: number
}

const WS_BASE = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000'

export function useWebSocket() {
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null)
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout>>()
  const token = useAuthStore(s => s.token)
  const isMock = import.meta.env.VITE_MOCK_DATA === 'true'

  const connect = useCallback(() => {
    if (isMock || !token) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    try {
      const ws = new WebSocket(`${WS_BASE}/ws`)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        clearTimeout(reconnectTimeout.current)
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as WsMessage
          if (msg.type !== 'heartbeat' && msg.type !== 'pong') {
            setLastMessage(msg)
          }
          if (msg.type === 'ping') ws.send(JSON.stringify({ type: 'pong' }))
        } catch {
          // ignore non-JSON frames
        }
      }

      ws.onclose = () => {
        setConnected(false)
        reconnectTimeout.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()
    } catch {
      // URL may be invalid in test environments — bail silently
    }
  }, [token, isMock])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimeout.current)
      wsRef.current?.close()
    }
  }, [connect])

  const send = useCallback((msg: WsMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  return { lastMessage, connected, send }
}

"use client"

import { useEffect, useRef, useState, useCallback } from "react"

interface UseWebSocketOptions {
  url: string
  onMessage?: (data: any) => void
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: (error: Event) => void
  onConnectionFailed?: () => void
  enabled?: boolean
  reconnectInterval?: number
  maxReconnectTime?: number
}

export function useWebSocket({
  url,
  onMessage,
  onConnect,
  onDisconnect,
  onError,
  onConnectionFailed,
  enabled = true,
  reconnectInterval = 1000,
  maxReconnectTime = 10000,
}: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false)
  const [connectionStatus, setConnectionStatus] = useState<"connecting" | "connected" | "disconnected" | "error">(
    "disconnected",
  )

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectStartTimeRef = useRef<number | null>(null)
  const isManuallyClosedRef = useRef(false)

  const connect = useCallback(() => {
    if (!enabled || wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    // Check if we've exceeded max reconnect time
    if (reconnectStartTimeRef.current) {
      const elapsed = Date.now() - reconnectStartTimeRef.current
      if (elapsed > maxReconnectTime) {
        onConnectionFailed?.()
        return
      }
    } else {
      reconnectStartTimeRef.current = Date.now()
    }

    setConnectionStatus("connecting")

    try {
      wsRef.current = new WebSocket(url)

      wsRef.current.onopen = () => {
        setIsConnected(true)
        setConnectionStatus("connected")
        reconnectStartTimeRef.current = null // Reset reconnect timer on successful connection
        onConnect?.()

        // Start ping interval
        pingIntervalRef.current = setInterval(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: "ping" }))
          }
        }, 30000)
      }

      wsRef.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          // Handle pong response
          if (data.type === "pong") {
            return
          }

          onMessage?.(data)
        } catch (error) {
          console.error("Failed to parse WebSocket message:", error)
        }
      }

      wsRef.current.onclose = (event) => {
        setIsConnected(false)
        setConnectionStatus("disconnected")
        onDisconnect?.()

        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
          pingIntervalRef.current = null
        }

        // Only attempt reconnection if not manually closed and enabled
        if (!isManuallyClosedRef.current && enabled) {
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, reconnectInterval)
        }
      }

      wsRef.current.onerror = (error) => {
        setConnectionStatus("error")
        onError?.(error)
      }
    } catch (error) {
      setConnectionStatus("error")
      console.error("WebSocket connection error:", error)
    }
  }, [
    url,
    enabled,
    onMessage,
    onConnect,
    onDisconnect,
    onError,
    onConnectionFailed,
    reconnectInterval,
    maxReconnectTime,
  ])

  const disconnect = useCallback(() => {
    isManuallyClosedRef.current = true

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
      pingIntervalRef.current = null
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    setIsConnected(false)
    setConnectionStatus("disconnected")
    reconnectStartTimeRef.current = null
  }, [])

  const sendMessage = useCallback((message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
      return true
    }
    return false
  }, [])

  useEffect(() => {
    if (enabled) {
      isManuallyClosedRef.current = false
      connect()
    } else {
      disconnect()
    }

    return () => {
      disconnect()
    }
  }, [enabled, connect, disconnect])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isManuallyClosedRef.current = true
      disconnect()
    }
  }, [disconnect])

  return {
    isConnected,
    connectionStatus,
    sendMessage,
    connect,
    disconnect,
  }
}

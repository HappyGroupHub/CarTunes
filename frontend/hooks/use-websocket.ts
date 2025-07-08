"use client"

import {useEffect, useRef, useState, useCallback} from "react"

interface UseWebSocketOptions {
    url: string
    onMessage?: (data: any) => void
    onConnect?: () => void
    onDisconnect?: () => void
    onError?: (error: Event) => void
    onConnectionFailed?: () => void
    enabled?: boolean
    reconnectInterval?: number
    maxReconnectAttempts?: number
    silentAudioRef?: React.RefObject<HTMLAudioElement>
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
                                 maxReconnectAttempts = 5,
                                 silentAudioRef,
                             }: UseWebSocketOptions) {
    const [isConnected, setIsConnected] = useState(false)
    const [connectionStatus, setConnectionStatus] = useState<"connecting" | "connected" | "disconnected" | "error">(
        "disconnected",
    )

    const wsRef = useRef<WebSocket | null>(null)
    const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const reconnectAttemptsRef = useRef(0)
    const isManuallyClosedRef = useRef(false)
    const connectionRetryDelayRef = useRef(reconnectInterval)

    const playSilentAudio = useCallback(() => {
        // This is specifically for prevent IOS mobile cleaning up the connection
        if (silentAudioRef?.current && 'mediaSession' in navigator) {
            silentAudioRef.current.loop = true;
            silentAudioRef.current.play().catch(e => console.error("Silent audio play failed:", e));
            console.log("Silent audio playing");
        }
    }, [silentAudioRef]);

    const stopSilentAudio = useCallback(() => {
        if (silentAudioRef?.current && 'mediaSession' in navigator) {
            silentAudioRef.current.pause();
            silentAudioRef.current.currentTime = 0;
            console.log("Silent audio stopped");
        }
    }, [silentAudioRef]);


    const connect = useCallback(() => {
        if (!enabled || wsRef.current?.readyState === WebSocket.OPEN) {
            return
        }

        // Check max reconnect attempts
        if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
            console.log("Max reconnect attempts reached")
            onConnectionFailed?.()
            return
        }

        setConnectionStatus("connecting")
        console.log(`WebSocket connecting... (attempt ${reconnectAttemptsRef.current + 1}/${maxReconnectAttempts})`)

        try {
            wsRef.current = new WebSocket(url)

            wsRef.current.onopen = () => {
                console.log("WebSocket connected successfully")
                setIsConnected(true)
                setConnectionStatus("connected")
                reconnectAttemptsRef.current = 0 // Reset on successful connection
                connectionRetryDelayRef.current = reconnectInterval // Reset delay
                onConnect?.()
            }

            wsRef.current.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data)
                    // Handle ping from server to play silent audio
                    if (data.type === 'ping') {
                        playSilentAudio();
                        sendMessage({type: 'pong'});
                        return;
                    }
                    if (data.type === 'playback_started') {
                        stopSilentAudio();
                    }
                    onMessage?.(data)
                } catch (error) {
                    console.error("Failed to parse WebSocket message:", error)
                }
            }

            wsRef.current.onclose = (event) => {
                console.log(`WebSocket closed: code=${event.code}, reason=${event.reason}`)
                setIsConnected(false)
                setConnectionStatus("disconnected")
                onDisconnect?.()
                stopSilentAudio();

                // Only attempt reconnection if not manually closed and enabled
                if (!isManuallyClosedRef.current && enabled) {
                    reconnectAttemptsRef.current++

                    if (reconnectAttemptsRef.current < maxReconnectAttempts) {
                        console.log(`Scheduling reconnect in ${connectionRetryDelayRef.current}ms...`)
                        reconnectTimeoutRef.current = setTimeout(() => {
                            connect()
                        }, connectionRetryDelayRef.current)

                        // Exponential backoff with jitter
                        connectionRetryDelayRef.current = Math.min(
                            connectionRetryDelayRef.current * 1.5 + Math.random() * 1000,
                            30000
                        )
                    } else {
                        onConnectionFailed?.()
                    }
                }
            }

            wsRef.current.onerror = (error) => {
                console.error("WebSocket error:", error)
                setConnectionStatus("error")
                onError?.(error)
                stopSilentAudio();
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
        maxReconnectAttempts,
        playSilentAudio,
        stopSilentAudio
    ])

    const disconnect = useCallback(() => {
        console.log("Manually disconnecting WebSocket")
        isManuallyClosedRef.current = true
        stopSilentAudio();

        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current)
            reconnectTimeoutRef.current = null
        }

        if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) {
            wsRef.current.close(1000, "Manual disconnect")
            wsRef.current = null
        }

        setIsConnected(false)
        setConnectionStatus("disconnected")
        reconnectAttemptsRef.current = 0
        connectionRetryDelayRef.current = reconnectInterval
    }, [reconnectInterval, stopSilentAudio])

    const sendMessage = useCallback((message: any) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(message))
            return true
        }
        console.warn("WebSocket not ready, message not sent:", message)
        return false
    }, [])

    useEffect(() => {
        if (enabled) {
            isManuallyClosedRef.current = false
            reconnectAttemptsRef.current = 0
            connectionRetryDelayRef.current = reconnectInterval
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
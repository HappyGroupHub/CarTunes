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
    silentAudioRef?: React.RefObject<HTMLAudioElement | null>
    onSilentAudioStateChange?: (isPlaying: boolean) => void
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
                                 onSilentAudioStateChange,
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
    const wasPageHiddenRef = useRef(false)
    const pageJustBecameVisibleRef = useRef(false)

    const playSilentAudio = useCallback(() => {
        // This is specifically for prevent IOS mobile cleaning up the connection
        if (silentAudioRef?.current && 'mediaSession' in navigator) {
            // Disable remote playback to prevent Media Session API from picking it up
            silentAudioRef.current.disableRemotePlayback = true;
            silentAudioRef.current.volume = 0;

            silentAudioRef.current.loop = true;
            silentAudioRef.current.play().catch(e => console.error("Silent audio play failed:", e));
            console.log("Silent audio playing");

            onSilentAudioStateChange?.(true);
        }
    }, [silentAudioRef, onSilentAudioStateChange]);

    const stopSilentAudio = useCallback(() => {
        if (silentAudioRef?.current && 'mediaSession' in navigator) {
            silentAudioRef.current.pause();
            silentAudioRef.current.currentTime = 0;
            console.log("Silent audio stopped");

            onSilentAudioStateChange?.(false);
        }
    }, [silentAudioRef, onSilentAudioStateChange]);


    const connect = useCallback(() => {
        if (!enabled || wsRef.current?.readyState === WebSocket.OPEN) {
            return
        }

        // Check max reconnect attempts
        if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
            console.log(`🚫 Max reconnect attempts reached (${reconnectAttemptsRef.current}/${maxReconnectAttempts})`)
            onConnectionFailed?.()
            return
        }

        setConnectionStatus("connecting")
        console.log(`🚀 Starting WebSocket connection attempt ${reconnectAttemptsRef.current + 1}/${maxReconnectAttempts}`)

        try {
            wsRef.current = new WebSocket(url)

            wsRef.current.onopen = () => {
                console.log("✅ WebSocket connected successfully!")
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
                console.log(`❌ WebSocket closed: code=${event.code}, reason=${event.reason}`)
                setIsConnected(false)
                setConnectionStatus("disconnected")
                onDisconnect?.()
                stopSilentAudio();

                // Check if page just became visible and reset manual close flag
                if (pageJustBecameVisibleRef.current) {
                    console.log("🔄 WebSocket closed after page became visible, resetting manual close flag")
                    isManuallyClosedRef.current = false
                }

                // Only attempt reconnection if not manually closed and enabled
                if (!isManuallyClosedRef.current && enabled) {
                    reconnectAttemptsRef.current++
                    console.log(`🔄 Planning reconnect attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts} in ${connectionRetryDelayRef.current}ms`)

                    if (reconnectAttemptsRef.current < maxReconnectAttempts) {
                        console.log(`⏰ Scheduling reconnect in ${connectionRetryDelayRef.current}ms...`)
                        reconnectTimeoutRef.current = setTimeout(() => {
                            console.log("⏲️ Reconnect timeout triggered, calling connect()")
                            connect()
                        }, connectionRetryDelayRef.current)

                        // Exponential backoff with jitter
                        connectionRetryDelayRef.current = Math.min(
                            connectionRetryDelayRef.current * 1.5 + Math.random() * 1000,
                            30000
                        )
                    } else {
                        console.log("💀 All reconnection attempts exhausted, calling onConnectionFailed")
                        onConnectionFailed?.()
                    }
                } else {
                    console.log(`🛑 No reconnection: manuallyClosedRef=${isManuallyClosedRef.current}, enabled=${enabled}`)
                }
            }

            wsRef.current.onerror = (error) => {
                console.error("⚠️ WebSocket error:", error)
                setConnectionStatus("error")
                onError?.(error)
            }
        } catch (error) {
            console.error("💥 Failed to create WebSocket:", error)
            setConnectionStatus("error")
        }
    }, [url, onMessage, onConnect, onDisconnect, onError, onConnectionFailed, enabled, reconnectInterval, maxReconnectAttempts, playSilentAudio, stopSilentAudio])

    const disconnect = useCallback(() => {
        isManuallyClosedRef.current = true
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current)
            reconnectTimeoutRef.current = null
        }
        if (wsRef.current) {
            wsRef.current.close()
            wsRef.current = null
        }
        stopSilentAudio()
    }, [stopSilentAudio])

    const sendMessage = useCallback((data: any) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(data))
        } else {
            console.warn("WebSocket is not connected. Cannot send message.")
        }
    }, [])

    useEffect(() => {
        const handleVisibilityChange = () => {
            if (document.hidden) {
                // Page is being hidden
                console.log("📱 Page is now hidden (user switched away)")
                wasPageHiddenRef.current = true
                pageJustBecameVisibleRef.current = false
            } else {
                // Page is now visible
                console.log("👀 Page is now visible (user returned)")
                pageJustBecameVisibleRef.current = true

                // Add a small delay to let WebSocket state settle
                setTimeout(() => {
                    if (wasPageHiddenRef.current && !isConnected && enabled) {
                        console.log("🔄 Page became visible while disconnected, attempting fresh reconnection")

                        // Reset reconnection state and manual close flag
                        reconnectAttemptsRef.current = 0
                        connectionRetryDelayRef.current = reconnectInterval
                        isManuallyClosedRef.current = false // Reset manual close flag

                        // Cancel any existing reconnection timeout
                        if (reconnectTimeoutRef.current) {
                            clearTimeout(reconnectTimeoutRef.current)
                            reconnectTimeoutRef.current = null
                        }

                        // Immediately attempt reconnection
                        connect()
                    } else {
                        console.log(`📊 No reconnection needed: wasHidden=${wasPageHiddenRef.current}, isConnected=${isConnected}, enabled=${enabled}`)
                    }

                    wasPageHiddenRef.current = false
                    pageJustBecameVisibleRef.current = false
                }, 500) // 500ms delay to let WebSocket state settle
            }
        }

        document.addEventListener('visibilitychange', handleVisibilityChange)

        return () => {
            document.removeEventListener('visibilitychange', handleVisibilityChange)
        }
    }, [isConnected, enabled, reconnectInterval, connect])

    // Handle disconnection that happens after page becomes visible
    useEffect(() => {
        if (!isConnected && pageJustBecameVisibleRef.current && enabled) {
            console.log("🔄 Detected disconnection after page became visible, forcing reconnection")

            // Reset flags and attempt reconnection
            isManuallyClosedRef.current = false
            reconnectAttemptsRef.current = 0
            connectionRetryDelayRef.current = reconnectInterval

            // Cancel any existing timeout
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current)
                reconnectTimeoutRef.current = null
            }

            // Attempt immediate reconnection
            connect()

            // Reset the flag
            pageJustBecameVisibleRef.current = false
        }
    }, [isConnected, enabled, reconnectInterval, connect])

    // Connect on mount if enabled
    useEffect(() => {
        if (enabled) {
            connect()
        }
        return () => {
            disconnect()
        }
    }, [enabled, connect, disconnect])

    return {
        isConnected,
        connectionStatus,
        sendMessage,
        disconnect,
        reconnect: connect,
        playSilentAudio,
        stopSilentAudio
    }
}
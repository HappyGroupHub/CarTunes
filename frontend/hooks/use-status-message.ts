"use client"

import React, {useCallback, useEffect, useRef, useState} from "react"

const FADE_START_DELAY = 2500
const CLEAR_DELAY = 3000

export interface StatusMessage {
    text: string
    color: string
    icon: React.ElementType | null
    // Mute button is hidden while its own feedback message is showing
    hidesMuteButton: boolean
}

interface ShowMessageOptions {
    icon?: React.ElementType | null
    hidesMuteButton?: boolean
}

// Shows a short-lived status message that fades out after a few seconds
export function useStatusMessage() {
    const [message, setMessage] = useState<StatusMessage | null>(null)
    const [opacity, setOpacity] = useState(1)
    const fadeTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const clearTimeoutRef = useRef<NodeJS.Timeout | null>(null)

    const clearTimers = () => {
        if (fadeTimeoutRef.current) clearTimeout(fadeTimeoutRef.current)
        if (clearTimeoutRef.current) clearTimeout(clearTimeoutRef.current)
    }

    const showMessage = useCallback((text: string, color: string, options: ShowMessageOptions = {}) => {
        clearTimers()
        setMessage({text, color, icon: options.icon ?? null, hidesMuteButton: options.hidesMuteButton ?? false})
        setOpacity(1)

        fadeTimeoutRef.current = setTimeout(() => {
            setOpacity(0)
        }, FADE_START_DELAY)

        clearTimeoutRef.current = setTimeout(() => {
            setMessage(null)
            setOpacity(1)
        }, CLEAR_DELAY)
    }, [])

    useEffect(() => clearTimers, [])

    return {message, opacity, showMessage}
}

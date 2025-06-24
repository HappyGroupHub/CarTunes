"use client"

import type React from "react"

import {useEffect, useState, useRef, useCallback} from "react"
import {useParams, useSearchParams, useRouter} from "next/navigation"
import {Button} from "@/components/ui/button"
import {Card, CardContent} from "@/components/ui/card"
import {Progress} from "@/components/ui/progress"
import {Badge} from "@/components/ui/badge"
import {
    Play,
    Pause,
    SkipForward,
    Music,
    User,
    Users,
    Wifi,
    WifiOff,
    Trash2,
    AlertCircle,
    Loader2,
    Download,
    VolumeX,
    Volume2,
    ArrowUpNarrowWide,
} from "lucide-react"
import {useWebSocket} from "@/hooks/use-websocket"
import {formatTime} from "@/lib/utils"
import {Modal} from "@/components/ui/modal"
import {API_ENDPOINTS} from "@/lib/config"
import {loadAudio} from "@/lib/audio-loader"

interface Song {
    id: string
    video_id: string
    title: string
    artist?: string
    duration: number
    thumbnail?: string
    requester_id: string
    requester_name: string
    added_at: string
}

interface PlaybackState {
    is_playing: boolean
    current_time: number
    last_updated: string
}

interface Room {
    room_id: string
    members: Array<{
        user_id: string
        user_name: string
        joined_at: string
    }>
    queue: Song[]
    current_song: Song | null
    playback_state: PlaybackState
    active_users: number
}

export default function RoomPage() {
    const params = useParams()
    const searchParams = useSearchParams()
    const router = useRouter()
    const roomId = params.roomId as string
    const userId = searchParams.get("userId") || ""

    const [room, setRoom] = useState<Room | null>(null)
    const [currentTime, setCurrentTime] = useState(0)
    const [isLoading, setIsLoading] = useState(true)
    const [showErrorModal, setShowErrorModal] = useState(false)
    const [errorMessage, setErrorMessage] = useState("")
    const [audioLoading, setAudioLoading] = useState(false)
    const [audioError, setAudioError] = useState<string | null>(null)
    const [songDownloading, setSongDownloading] = useState(false)
    const [hasUserInteractedWithPlayButton, setHasUserInteractedWithPlayButton] = useState(false)

    const [isMuted, setIsMuted] = useState(false)
    const [muteMessage, setMuteMessage] = useState<string | null>(null)
    const [messageOpacity, setMessageOpacity] = useState(1)
    const messageTimeoutRef = useRef<NodeJS.Timeout | null>(null)

    const audioRef = useRef<HTMLAudioElement>(null)
    const progressIntervalRef = useRef<NodeJS.Timeout | null>(null)
    const audioLoaderCleanupRef = useRef<(() => void) | null>(null)

    // Refs to hold the latest state values for stable callbacks
    const roomRef = useRef<Room | null>(null)
    const audioErrorRef = useRef<string | null>(null)
    const songDownloadingRef = useRef<boolean>(false)
    const hasUserInteractedWithPlayButtonRef = useRef<boolean>(false)

    // State for swipe-to-delete
    const [swipedSongId, setSwipedSongId] = useState<string | null>(null)
    const touchStartX = useRef(0)
    const touchCurrentX = useRef(0)
    const swipeThreshold = 50 // Pixels to swipe to reveal delete button

    // State for audio status checking
    const [audioStatusChecking, setAudioStatusChecking] = useState<Set<string>>(new Set())
    const audioStatusCheckingRef = useRef<Set<string>>(new Set())
    const statusCheckIntervalsRef = useRef<Map<string, NodeJS.Timeout>>(new Map())

    useEffect(() => {
        roomRef.current = room
    }, [room])

    useEffect(() => {
        audioErrorRef.current = audioError
    }, [audioError])

    useEffect(() => {
        songDownloadingRef.current = songDownloading
    }, [songDownloading])

    useEffect(() => {
        hasUserInteractedWithPlayButtonRef.current = hasUserInteractedWithPlayButton
    }, [hasUserInteractedWithPlayButton])

    // Callbacks for audio-loader, made stable by not depending on 'room' directly
    const handleLoadedMetadata = useCallback((audioElement: HTMLAudioElement, initialTime: number) => {
        audioElement.currentTime = initialTime
    }, [])

    const handleCanPlay = useCallback(
        (audioElement: HTMLAudioElement, isPlaying: boolean, userHasInteracted: boolean) => {
            if (userHasInteracted && isPlaying && audioElement.paused) {
                audioElement.play().catch((e) => console.error("Autoplay blocked on canplay:", e))
            }
        },
        [], // No dependencies
    )

    const loadAudioForCurrentSong = useCallback(
        async (videoId: string, initialTime: number, isPlaying: boolean, userHasInteracted: boolean) => {
            if (audioLoaderCleanupRef.current) {
                audioLoaderCleanupRef.current() // Clean up previous audio loading
                audioLoaderCleanupRef.current = null
            }

            if (audioRef.current) {
                audioLoaderCleanupRef.current = loadAudio(audioRef.current, videoId, {
                    setAudioLoading,
                    setAudioError,
                    setSongDownloading,
                    onLoadedMetadata: (el) => handleLoadedMetadata(el, initialTime),
                    onCanPlay: (el) => handleCanPlay(el, isPlaying, userHasInteracted),
                })
            }
        },
        [handleLoadedMetadata, handleCanPlay, setAudioLoading, setAudioError, setSongDownloading],
    )

    const handleWebSocketMessage = useCallback(
        (data: any) => {
            const currentRoom = roomRef.current // Access the latest room state via ref
            const currentAudioError = audioErrorRef.current
            const currentSongDownloading = songDownloadingRef.current
            const currentUserInteracted = hasUserInteractedWithPlayButtonRef.current

            console.log("WebSocket message:", data)
            const messageType = typeof data.type === "string" ? data.type.toUpperCase() : data.type

            switch (messageType) {
                case "ROOM_STATE":
                    const roomData = data.data.room
                    const previousSong = roomRef.current?.current_song
                    const newSong = roomData.current_song

                    setRoom((prev) => ({
                        room_id: roomData.room_id,
                        members: roomData.members,
                        queue: roomData.queue,
                        current_song: roomData.current_song,
                        // Preserve current_time if song is the same and currently playing
                        playback_state:
                            prev?.current_song?.id === roomData.current_song?.id && prev?.playback_state.is_playing
                                ? {
                                    ...roomData.playback_state,
                                    current_time: prev.playback_state.current_time, // Keep current progress
                                }
                                : roomData.playback_state,
                        active_users: prev?.active_users || 0,
                    }))

                    // Only reload audio if the current song actually changed
                    const songChanged = previousSong?.id !== newSong?.id

                    if (songChanged && newSong && audioRef.current) {
                        // Song actually changed, reload audio
                        loadAudioForCurrentSong(
                            newSong.video_id,
                            roomData.playback_state.current_time || 0,
                            roomData.playback_state.is_playing || false,
                            currentUserInteracted,
                        )
                    }
                    // If song didn't change, don't reload audio
                    break

                case "SONG_CHANGED":
                    setRoom((prev) => {
                        if (!prev) return null

                        return {
                            ...prev,
                            current_song: data.data.current_song,
                            // Reset current_time when song changes
                            playback_state: {
                                ...prev.playback_state,
                                current_time: 0,
                                // Don't automatically set to playing - let the backend decide
                                // The backend will send a separate PLAYBACK_STATE_CHANGED message if needed
                            },
                        }
                    })

                    // Handle both new song and no song cases
                    if (data.data.current_song && audioRef.current) {
                        // Load new audio when song changes to a new song
                        // Don't auto-play - wait for user interaction or backend playback state
                        loadAudioForCurrentSong(
                            data.data.current_song.video_id,
                            0, // Start from beginning
                            false, // Don't auto-play - let backend control this
                            currentUserInteracted,
                        )

                        // START STATUS CHECK IMMEDIATELY when new song appears
                        console.log("New song detected, starting status check")
                        checkAudioStatus(data.data.current_song.video_id)

                    } else if (!data.data.current_song && audioRef.current) {
                        // Pause and clear audio when no current song
                        audioRef.current.pause()
                        audioRef.current.src = ""
                        setCurrentTime(0)
                        setAudioError(null)
                        setAudioLoading(false)
                        setSongDownloading(false)

                        // Clean up any ongoing audio loading
                        if (audioLoaderCleanupRef.current) {
                            audioLoaderCleanupRef.current()
                            audioLoaderCleanupRef.current = null
                        }
                    }
                    break

                case "SONG_ADDED":
                    setRoom((prev) => {
                        if (!prev) return null

                        return {
                            ...prev,
                            queue: [...prev.queue, data.data.song],
                            // FIXED: Don't touch playback_state when adding songs to queue
                        }
                    })
                    break

                case "SONG_REMOVED":
                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                queue: prev.queue.filter((song) => song.id !== data.data.song_id),
                            }
                            : null,
                    )
                    break

                case "QUEUE_REORDERED":
                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                queue: data.data.queue,
                            }
                            : null,
                    )
                    break

                case "PLAYBACK_STATE_CHANGED":
                    console.log("Playback state changed:", data.data)
                    const newIsPlaying = data.data.is_playing
                    const newCurrentTime = data.data.current_time

                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                playback_state: {
                                    ...prev.playback_state,
                                    is_playing: newIsPlaying,
                                    current_time: newCurrentTime !== undefined ? newCurrentTime : prev.playback_state.current_time,
                                },
                            }
                            : null,
                    )

                    // Handle audio playback sync
                    if (audioRef.current && currentRoom?.current_song) {
                        if (newIsPlaying) {
                            // Backend wants audio to play
                            if (currentUserInteracted) {
                                // Set time first if provided
                                if (newCurrentTime !== undefined && Math.abs(audioRef.current.currentTime - newCurrentTime) > 2) {
                                    audioRef.current.currentTime = newCurrentTime
                                }

                                // Try to play, but handle the case where audio might not be ready
                                const playPromise = audioRef.current.play()
                                if (playPromise !== undefined) {
                                    playPromise.catch(err => {
                                        console.log("Play failed, probably audio not ready yet:", err)
                                        // If play fails, try again after a short delay
                                        setTimeout(() => {
                                            if (audioRef.current && roomRef.current?.playback_state.is_playing) {
                                                audioRef.current.play().catch(e => console.log("Retry play failed:", e))
                                            }
                                        }, 500)
                                    })
                                }
                            }
                            // If user hasn't interacted, we can't auto-play due to browser restrictions
                        } else {
                            // Backend wants audio to pause
                            audioRef.current.pause()
                            if (newCurrentTime !== undefined && Math.abs(audioRef.current.currentTime - newCurrentTime) > 2) {
                                audioRef.current.currentTime = newCurrentTime
                            }
                        }
                    }
                    break

                case "PLAYBACK_SEEKED":
                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                playback_state: {
                                    ...prev.playback_state,
                                    current_time: data.data.current_time,
                                },
                            }
                            : null,
                    )
                    // Sync audio element time
                    if (audioRef.current) {
                        audioRef.current.currentTime = data.data.current_time
                    }
                    break

                case "USER_JOINED":
                    // Just a notification - don't modify state
                    // The ROOM_STATS_UPDATE message will handle active_users count
                    // The ROOM_STATE message will handle members list updates
                    break

                case "USER_LEFT":
                    // Just a notification - don't modify state
                    // The ROOM_STATS_UPDATE message will handle active_users count
                    // The ROOM_STATE message will handle members list updates
                    break

                case "ROOM_STATS_UPDATE":
                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                active_users: data.data.active_users,
                            }
                            : null,
                    )
                    break

                case "PLAYBACK_STARTED":
                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                playback_state: {
                                    ...prev.playback_state,
                                    is_playing: true,
                                    current_time: data.data.current_time || prev.playback_state.current_time,
                                },
                            }
                            : null,
                    )
                    // Handle audio playback - check if audio is ready first
                    if (audioRef.current && currentUserInteracted) {
                        if (data.data.current_time !== undefined) {
                            audioRef.current.currentTime = data.data.current_time
                        }

                        // Check if audio is ready to play
                        if (audioRef.current.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
                            // Audio is ready, play immediately
                            audioRef.current.play().catch((e) => console.error("Autoplay blocked on PLAYBACK_STARTED:", e))
                        } else {
                            // Audio not ready yet, wait for it to load
                            const handleCanPlay = () => {
                                if (audioRef.current && roomRef.current?.playback_state.is_playing) {
                                    audioRef.current.play().catch((e) => console.error("Delayed autoplay blocked:", e))
                                }
                                audioRef.current?.removeEventListener('canplay', handleCanPlay)
                            }
                            audioRef.current.addEventListener('canplay', handleCanPlay)
                        }
                    }
                    break

                case "PLAYBACK_PAUSED":
                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                playback_state: {
                                    ...prev.playback_state,
                                    is_playing: false,
                                    current_time: data.data.current_time !== undefined ? data.data.current_time : prev.playback_state.current_time,
                                },
                            }
                            : null,
                    )
                    // Handle audio pause
                    if (audioRef.current) {
                        audioRef.current.pause()
                        if (data.data.current_time !== undefined && Math.abs(audioRef.current.currentTime - data.data.current_time) > 2) {
                            audioRef.current.currentTime = data.data.current_time
                        }
                    }
                    break

                case "PLAYBACK_PROGRESS":
                    const progressTime = data.data.current_time

                    // Handle negative time (loading delay) - show 0:00
                    if (progressTime < 0) {
                        setCurrentTime(0)  // Always show 0 for negative time

                        // Status check should already be running from SONG_CHANGED
                        // No need to start it again here
                        break
                    }

                    // Normal positive time - update as usual
                    setCurrentTime(progressTime)

                    // Smart logic: If backend just reached 0 from negative, try to start audio
                    if (audioRef.current && progressTime >= 0 && progressTime < 0.5 && currentRoom?.current_song) {
                        const isActuallyPlaying = !audioRef.current.paused
                        const videoId = currentRoom.current_song.video_id

                        // Stop status checking if still active (audio should be ready now)
                        if (audioStatusCheckingRef.current.has(videoId)) {
                            const interval = statusCheckIntervalsRef.current.get(videoId)
                            if (interval) {
                                clearInterval(interval)
                                statusCheckIntervalsRef.current.delete(videoId)
                            }
                            audioStatusCheckingRef.current.delete(videoId)
                            setSongDownloading(false) // Clear downloading state
                        }

                        if (!isActuallyPlaying && currentUserInteracted && !songDownloading) {
                            // Backend reached 0 and audio should be ready - start playing
                            console.log("Backend reached 0, starting audio")
                            audioRef.current.currentTime = progressTime
                            audioRef.current.play().catch(e => console.log("Failed to start audio at 0:", e))
                        }
                    } else if (audioRef.current && progressTime > 0.5) {
                        // Normal sync logic for positive times
                        const isActuallyPlaying = !audioRef.current.paused

                        if (!isActuallyPlaying && currentUserInteracted && roomRef.current?.playback_state.is_playing && !songDownloading) {
                            console.log("Audio should be playing but isn't - starting")
                            audioRef.current.currentTime = progressTime
                            audioRef.current.play().catch(e => console.log("Failed to start stalled audio:", e))
                        } else if (isActuallyPlaying && Math.abs(audioRef.current.currentTime - progressTime) > 2) {
                            console.log(`Resyncing playing audio: local ${audioRef.current.currentTime.toFixed(2)}, remote ${progressTime.toFixed(2)}`)
                            audioRef.current.currentTime = progressTime
                        }
                    }
                    break

                case "ERROR":
                    console.error("WebSocket error:", data.data)
                    setErrorMessage(data.data.message || "發生未知錯誤")
                    setShowErrorModal(true)
                    break

                case "ROOM_CLOSING":
                    setErrorMessage("房間已關閉")
                    setShowErrorModal(true)
                    break

                default:
                    console.log("Unhandled WebSocket message type:", data.type)
                    break
            }
        },
        [loadAudioForCurrentSong, setErrorMessage, setShowErrorModal],
    )

    const checkAudioStatus = useCallback(async (videoId: string) => {
        if (audioStatusCheckingRef.current.has(videoId)) {
            return // Already checking this video
        }

        console.log(`Starting status check for ${videoId} in room ${roomId}`)

        audioStatusCheckingRef.current.add(videoId)
        setAudioStatusChecking(prev => new Set([...prev, videoId]))

        const checkStatus = async () => {
            try {
                const url = API_ENDPOINTS.AUDIO_STATUS(videoId, roomId)
                console.log(`Checking status at: ${url}`)

                const response = await fetch(url)
                console.log(`Status response:`, response.status, response.ok)

                if (response.ok) {
                    const data = await response.json()
                    console.log(`Status data:`, data)

                    if (data.status === "downloading") {
                        setSongDownloading(true)
                        setAudioLoading(false)
                        setAudioError(null)
                        return false
                    } else if (data.status === "ready") {
                        // Audio is ready - IMMEDIATELY clear checking state
                        console.log(`✅ Audio ready for ${videoId}, clearing status check`)

                        // Clear interval and tracking
                        const interval = statusCheckIntervalsRef.current.get(videoId)
                        if (interval) {
                            clearInterval(interval)
                            statusCheckIntervalsRef.current.delete(videoId)
                        }

                        audioStatusCheckingRef.current.delete(videoId)
                        setAudioStatusChecking(prev => {
                            const newSet = new Set(prev)
                            newSet.delete(videoId)
                            return newSet
                        })

                        setSongDownloading(false)
                        return true
                    }
                } else {
                    console.error(`Status check failed with status:`, response.status)
                }
            } catch (error) {
                console.error(`Status check failed for ${videoId}:`, error)
            }
            return false
        }

        // Check immediately
        const isReady = await checkStatus()
        if (isReady) return

        // If not ready, poll every 1 second
        const interval = setInterval(async () => {
            const ready = await checkStatus()
            if (ready) {
                clearInterval(interval)
                statusCheckIntervalsRef.current.delete(videoId)
            }
        }, 1000)
        statusCheckIntervalsRef.current.set(videoId, interval)
    }, [roomId])

    const {isConnected, connectionStatus} = useWebSocket({
        url: `${API_ENDPOINTS.WEBSOCKET(roomId)}?user_id=${userId}`,
        onMessage: handleWebSocketMessage,
        onConnect: useCallback(() => {
            console.log("WebSocket connected successfully")
        }, []),
        onDisconnect: useCallback(() => {
            console.log("WebSocket disconnected")
        }, []),
        onConnectionFailed: useCallback(() => {
            setErrorMessage("連線失敗，請檢查網路連線後重新整理頁面")
            setShowErrorModal(true)
        }, [setErrorMessage, setShowErrorModal]),
        enabled: !isLoading && room !== null,
        reconnectInterval: 2000,
        maxReconnectAttempts: 3,
    })

    useEffect(() => {
        return () => {
            // Cleanup status checking intervals
            statusCheckIntervalsRef.current.forEach(interval => clearInterval(interval))
            statusCheckIntervalsRef.current.clear()
        }
    }, [])

    useEffect(() => {
        checkRoomExists()
    }, [roomId])

    async function checkRoomExists() {
        try {
            const response = await fetch(API_ENDPOINTS.ROOM(roomId))
            if (!response.ok) {
                setErrorMessage("不存在的房間")
                setShowErrorModal(true)
                return
            }

            const roomData = await response.json()
            setRoom(roomData)
            setCurrentTime(roomData.playback_state.current_time || 0) // Initialize currentTime from backend
            setIsLoading(false)

            if (roomData.current_song) {
                await loadAudioForCurrentSong(
                    roomData.current_song.video_id,
                    roomData.playback_state.current_time,
                    roomData.playback_state.is_playing,
                    hasUserInteractedWithPlayButtonRef.current,
                )
            }
        } catch (err) {
            setErrorMessage("不存在的房間")
            setShowErrorModal(true)
        }
    }

    async function togglePlayback() {
        if (!room?.current_song || audioError || songDownloading) {
            console.log("Cannot play due to no current song, audio error, or downloading")
            return
        }

        const audioEl = audioRef.current
        if (!audioEl) return

        const roomIsPlaying = room.playback_state.is_playing // Backend's view of playback
        const localAudioIsPlaying = !audioEl.paused // Local audio element's view

        // Set user interaction flag immediately
        setHasUserInteractedWithPlayButton(true)
        hasUserInteractedWithPlayButtonRef.current = true

        if (!roomIsPlaying) {
            // Scenario 1: Room is NOT playing music (backend says paused)
            // User clicks play -> start room music
            try {
                await audioEl.play() // Attempt local play
                console.log("Local audio play initiated (Room was paused).")
                // If local play succeeds, update backend to start room music
                setRoom((prev) =>
                    prev
                        ? {
                            ...prev,
                            playback_state: {
                                ...prev.playback_state,
                                is_playing: true,
                                current_time: audioEl.currentTime,
                            },
                        }
                        : null,
                )
                await fetch(`${API_ENDPOINTS.PLAYBACK(roomId)}?user_id=${userId}`, {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        is_playing: true,
                        current_time: audioEl.currentTime,
                    }),
                })
            } catch (e) {
                console.error("Error playing audio (Room was paused, autoplay blocked):", e)
                setAudioError("播放失敗 (自動播放被阻擋或錯誤)")
                // Revert local UI state if play failed
                setRoom((prev) =>
                    prev
                        ? {
                            ...prev,
                            playback_state: {
                                ...prev.playback_state,
                                is_playing: false,
                            },
                        }
                        : null,
                )
            }
        } else {
            // Room IS playing music (backend says playing)
            if (!localAudioIsPlaying) {
                // Scenario 2: Local audio is NOT playing (new user, autoplay blocked)
                // User clicks play -> only start local audio, do NOT send backend command
                try {
                    // Fetch latest current_time before playing to ensure accurate sync
                    const response = await fetch(`${API_ENDPOINTS.ROOM(roomId)}`)
                    const latestRoomData = await response.json()
                    const latestCurrentTime = latestRoomData.playback_state.current_time

                    audioEl.currentTime = latestCurrentTime // Sync local audio to latest room time
                    await audioEl.play()
                    console.log("Local audio play initiated (Room was already playing).")
                    // Update local state to reflect playing, but don't send backend command
                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                playback_state: {
                                    ...prev.playback_state,
                                    is_playing: true, // Local audio is now playing
                                    current_time: latestCurrentTime,
                                },
                            }
                            : null,
                    )
                } catch (e) {
                    console.error("Error playing audio (Room was already playing, autoplay blocked):", e)
                    setAudioError("播放失敗 (自動播放被阻擋或錯誤)")
                    // Revert local UI state if play failed
                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                playback_state: {
                                    ...prev.playback_state,
                                    is_playing: false,
                                },
                            }
                            : null,
                    )
                }
            } else {
                // Scenario 3: Local audio IS playing (user wants to pause)
                // User clicks pause -> pause room music
                audioEl.pause()
                console.log("Local audio paused.")
                // Update local state and send update to backend
                setRoom((prev) =>
                    prev
                        ? {
                            ...prev,
                            playback_state: {
                                ...prev.playback_state,
                                is_playing: false,
                                current_time: audioEl.currentTime,
                            },
                        }
                        : null,
                )
                await fetch(`${API_ENDPOINTS.PLAYBACK(roomId)}?user_id=${userId}`, {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        is_playing: false,
                        current_time: audioEl.currentTime,
                    }),
                })
            }
        }
    }

    async function skipToNext() {
        try {
            await fetch(`${API_ENDPOINTS.SKIP_NEXT(roomId)}?user_id=${userId}`, {
                method: "POST",
            })
        } catch (err) {
            console.error("Failed to skip song:", err)
        }
    }

    async function removeSong(songId: string) {
        try {
            await fetch(`${API_ENDPOINTS.REMOVE_SONG(roomId, songId)}?user_id=${userId}`, {
                method: "DELETE",
            })
            setSwipedSongId(null) // Close swipe after deletion
        } catch (err) {
            console.error("Failed to remove song:", err)
        }
    }

    async function bringSongToTop(songId: string) {
        if (!room) return
        const currentQueue = room.queue
        const songToMove = currentQueue.find((s) => s.id === songId)
        if (!songToMove) return

        const newQueue = [songToMove, ...currentQueue.filter((s) => s.id !== songId)]
        const newSongIds = newQueue.map((s) => s.id)

        try {
            await fetch(`${API_ENDPOINTS.REORDER_QUEUE(roomId)}?user_id=${userId}`, {
                method: "PUT",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({song_ids: newSongIds}),
            })
            // Optimistic update or wait for WebSocket ROOM_STATE/QUEUE_REORDERED
            setRoom((prev) => (prev ? {...prev, queue: newQueue} : null))
        } catch (err) {
            console.error("Failed to bring song to top:", err)
            // Revert optimistic update if needed
        }
    }

    // This useEffect will manage the local progress bar update
    useEffect(() => {
        if (room?.playback_state.is_playing) {
            // Initialize currentTime but never show negative
            setCurrentTime(Math.max(0, room.playback_state.current_time))

            // Start a local interval to increment currentTime
            progressIntervalRef.current = setInterval(() => {
                setCurrentTime((prevTime) => Math.max(0, prevTime + 1)) // Never go negative
            }, 1000)
        } else {
            // If not playing, clear the interval
            if (progressIntervalRef.current) {
                clearInterval(progressIntervalRef.current)
                progressIntervalRef.current = null
            }
            // When paused, ensure currentTime reflects the last known backend time (but not negative)
            if (room) {
                setCurrentTime(Math.max(0, room.playback_state.current_time))
            }
        }

        return () => {
            if (progressIntervalRef.current) {
                clearInterval(progressIntervalRef.current)
            }
        }
    }, [room?.current_song?.id, room?.playback_state.is_playing])

    useEffect(() => {
        return () => {
            if (audioLoaderCleanupRef.current) {
                audioLoaderCleanupRef.current()
            }
            if (progressIntervalRef.current) {
                clearInterval(progressIntervalRef.current)
            }
        }
    }, [])

    const handleErrorModalClose = () => {
        setShowErrorModal(false)
        router.push("/")
    }

    const toggleMute = () => {
        if (audioRef.current) {
            const newState = !isMuted
            audioRef.current.muted = newState
            setIsMuted(newState)

            // Clear any existing timeout
            if (messageTimeoutRef.current) {
                clearTimeout(messageTimeoutRef.current)
            }

            const message = newState ? "音樂已在此裝置靜音" : "開始在裝置播放音樂"
            setMuteMessage(message)
            setMessageOpacity(1) // Ensure message is fully visible when it appears

            // Set timeout to start fading after 2.5 seconds
            messageTimeoutRef.current = setTimeout(() => {
                setMessageOpacity(0)
            }, 2500)

            // Set timeout to clear message completely after 3 seconds (0.5s fade + 2.5s delay)
            messageTimeoutRef.current = setTimeout(() => {
                setMuteMessage(null)
                setMessageOpacity(1) // Reset opacity for next message
            }, 3000)
        }
    }

    // Swipe handlers
    const handleTouchStart = (e: React.TouchEvent, songId: string) => {
        setSwipedSongId(null) // Close any currently swiped item
        touchStartX.current = e.touches[0].clientX
        touchCurrentX.current = e.touches[0].clientX
    }

    const handleTouchMove = (e: React.TouchEvent, songId: string) => {
        touchCurrentX.current = e.touches[0].clientX
        const deltaX = touchCurrentX.current - touchStartX.current

        if (deltaX < -swipeThreshold) {
            // Swiping left
            setSwipedSongId(songId)
        } else if (deltaX > swipeThreshold) {
            // Swiping right
            setSwipedSongId(null)
        }
    }

    const handleTouchEnd = (songId: string) => {
        const deltaX = touchCurrentX.current - touchStartX.current
        if (Math.abs(deltaX) < swipeThreshold) {
            setSwipedSongId(null) // Close if not swiped enough
        }
        touchStartX.current = 0 // Reset for next interaction
        touchCurrentX.current = 0 // Reset currentX as well
    }

    // Mouse handlers for desktop (simulating touch)
    const handleMouseDown = (e: React.MouseEvent, songId: string) => {
        setSwipedSongId(null) // Close any currently swiped item
        touchStartX.current = e.clientX
        touchCurrentX.current = e.clientX
    }

    const handleMouseMove = (e: React.MouseEvent, songId: string) => {
        if (touchStartX.current !== 0) {
            // Only if drag started
            touchCurrentX.current = e.clientX
            const deltaX = touchCurrentX.current - touchStartX.current
            if (deltaX < -swipeThreshold) {
                setSwipedSongId(songId)
            } else if (deltaX > swipeThreshold) {
                setSwipedSongId(null)
            }
        }
    }

    const handleMouseUp = () => {
        if (touchStartX.current !== 0) {
            const deltaX = touchCurrentX.current - touchStartX.current
            if (Math.abs(deltaX) < swipeThreshold) {
                setSwipedSongId(null)
            }
            touchStartX.current = 0 // Reset for next drag
            touchCurrentX.current = 0 // Reset currentX as well
        }
    }

    const handleMouseLeave = () => {
        // Reset if mouse leaves while dragging
        if (touchStartX.current !== 0) {
            setSwipedSongId(null)
            touchStartX.current = 0
            touchCurrentX.current = 0
        }
    }

    if (isLoading) {
        return (
            <div
                className="min-h-screen bg-gradient-to-br from-purple-600 via-blue-600 to-cyan-600 flex items-center justify-center">
                <div className="text-white text-center">
                    <Music className="h-12 w-12 mx-auto mb-4 animate-pulse" strokeWidth={2}/>
                    <p>檢查房間中...</p>
                </div>
            </div>
        )
    }

    if (!room) return null

    const progress = room.current_song ? (currentTime / room.current_song.duration) * 100 : 0

    return (
        <div className="min-h-screen bg-gradient-to-br from-purple-600 via-blue-600 to-cyan-600">
            <audio ref={audioRef} preload="metadata" crossOrigin="anonymous"/>

            {/* Error Modal */}
            <Modal isOpen={showErrorModal} onClose={handleErrorModalClose} title="提示">
                <div className="text-center py-4">
                    <p className="text-gray-700 mb-6">{errorMessage}</p>
                    <Button onClick={handleErrorModalClose} className="w-full">
                        確認
                    </Button>
                </div>
            </Modal>

            {/* Header */}
            <div className="bg-black/20 backdrop-blur-sm p-4">
                <div className="flex items-center justify-between max-w-md mx-auto">
                    <div className="flex items-center space-x-2">
                        <Music className="h-6 w-6 text-white" strokeWidth={2}/>
                        <span className="text-white font-semibold">房間 {roomId}</span>
                        {/* Mute Button */}
                        <Button
                            onClick={toggleMute}
                            size="icon"
                            variant="ghost"
                            className={`${isMuted ? "text-red-500 hover:bg-red-500/20" : "text-white hover:bg-white/20"} w-8 h-8`}
                            aria-label={isMuted ? "Unmute audio" : "Mute audio"}
                        >
                            {isMuted ? <VolumeX className="h-4 w-4"/> : <Volume2 className="h-4 w-4"/>}
                        </Button>
                        {/* Mute Message */}
                        {muteMessage && (
                            <span
                                className={`${isMuted ? "text-red-500" : "text-white"} text-sm ml-2 transition-opacity duration-500 ease-out`}
                                style={{opacity: messageOpacity}}
                            >
                {muteMessage}
              </span>
                        )}
                    </div>
                    <div className="flex items-center space-x-2">
                        {isConnected ? (
                            <Wifi className="h-4 w-4 text-green-400" strokeWidth={2}/>
                        ) : (
                            <WifiOff className="h-4 w-4 text-red-400" strokeWidth={2}/>
                        )}
                        <Badge variant="secondary" className="bg-white/20 text-white">
                            <Users className="h-3 w-3 mr-1" strokeWidth={2}/>
                            {room.active_users}
                        </Badge>
                    </div>
                </div>
            </div>

            <div className="max-w-md mx-auto p-4 space-y-4">
                {/* Current Song */}
                <Card className="bg-white/10 backdrop-blur-sm border-white/20">
                    <CardContent className="p-3 flex flex-col">
                        {room.current_song ? (
                            <>
                                <div className="flex items-center mb-3">
                                    {/* Song Thumbnail */}
                                    {room.current_song.thumbnail && (
                                        <img
                                            src={room.current_song.thumbnail || "/placeholder.svg"}
                                            alt={room.current_song.title}
                                            className="w-28 h-28 rounded-lg object-cover mr-4"
                                        />
                                    )}
                                    {/* Song Info (Title, Artist, Requester) */}
                                    <div className="flex-1 min-w-0 text-left">
                                        <h2 className="text-white font-bold text-base line-clamp-2 mb-1">{room.current_song.title}</h2>
                                        {room.current_song.artist && (
                                            <p className="text-white/70 text-sm truncate mb-1">{room.current_song.artist}</p>
                                        )}
                                        <div className="flex items-center space-x-1 text-white/60 text-xs">
                                            <User className="h-3 w-3" strokeWidth={2}/>
                                            <span>{room.current_song.requester_name}</span>
                                        </div>
                                    </div>
                                </div>

                                {/* Audio Status Indicators */}
                                {(songDownloading || audioLoading || audioError || (room?.current_song && audioStatusCheckingRef.current.has(room.current_song.video_id))) && (
                                    <div className="flex items-center justify-center space-x-2 mt-2 mb-2 text-sm">
                                        {songDownloading && (
                                            <span className="text-blue-400 flex items-center">
                <Download className="h-4 w-4 animate-bounce mr-1" strokeWidth={2}/>
                音訊載入中...
            </span>
                                        )}
                                        {(room?.current_song && audioStatusCheckingRef.current.has(room.current_song.video_id)) && !songDownloading && (
                                            <span className="text-yellow-400 flex items-center">
                <Loader2 className="h-4 w-4 animate-spin mr-1" strokeWidth={2}/>
                檢查音訊狀態...
            </span>
                                        )}
                                        {audioLoading && !songDownloading && !(room?.current_song && audioStatusCheckingRef.current.has(room.current_song.video_id)) && (
                                            <span className="text-white/60 flex items-center">
                <Loader2 className="h-4 w-4 animate-spin mr-1" strokeWidth={2}/>
                音訊載入中...
            </span>
                                        )}
                                        {audioError && !songDownloading && (
                                            <span className="text-red-400 flex items-center">
                <AlertCircle className="h-4 w-4 mr-1" strokeWidth={2}/>
                                                {audioError}
            </span>
                                        )}
                                    </div>
                                )}

                                {/* Progress bar and controls on one line */}
                                <div className="flex items-center space-x-2 mt-1">
                                    {/* Progress bar and time labels grouped together */}
                                    <div className="flex-1">
                                        <Progress value={progress} className="h-1"/>
                                        <div className="flex justify-between text-white/60 text-xs mt-0.5">
                                            <span>{formatTime(Math.floor(Math.max(0, currentTime)))}</span>
                                            <span>{formatTime(room.current_song.duration)}</span>
                                        </div>
                                    </div>
                                    {/* Controls */}
                                    <div className="flex flex-col justify-start">
                                        <div className="flex items-center space-x-2 -mt-4">
                                            <Button
                                                onClick={togglePlayback}
                                                disabled={
                                                    audioLoading ||
                                                    !!audioError ||
                                                    songDownloading ||
                                                    (room?.current_song && audioStatusCheckingRef.current.has(room.current_song.video_id))
                                                }
                                                size="icon"
                                                className="bg-white/20 hover:bg-white/30 text-white rounded-full w-10 h-10 disabled:opacity-50 disabled:cursor-not-allowed"
                                            >
                                                {room.playback_state.is_playing && hasUserInteractedWithPlayButton ? (
                                                    <Pause className="h-5 w-5" strokeWidth={2}/>
                                                ) : (
                                                    <Play className="h-5 w-5" strokeWidth={2}/>
                                                )}
                                            </Button>
                                            <Button
                                                onClick={skipToNext}
                                                size="icon"
                                                className="bg-white/20 hover:bg-white/30 text-white rounded-full w-10 h-10"
                                            >
                                                <SkipForward className="h-5 w-5" strokeWidth={2}/>
                                            </Button>
                                        </div>
                                    </div>
                                </div>
                            </>
                        ) : (
                            <div className="text-center text-white/60 py-8">
                                <Music className="h-12 w-12 mx-auto mb-4 opacity-50" strokeWidth={2}/>
                                <p>目前沒有播放歌曲</p>
                                <p className="text-sm mt-2">透過 LINE Bot 點歌開始播放</p>
                            </div>
                        )}
                    </CardContent>
                </Card>

                {/* Queue */}
                <Card className="bg-white/10 backdrop-blur-sm border-white/20">
                    <CardContent className="p-4">
                        <h3 className="text-white font-semibold mb-4 flex items-center">
                            <Music className="h-4 w-4 mr-2" strokeWidth={2}/>
                            播放清單 ({room.queue.length})
                        </h3>

                        {room.queue.length > 0 ? (
                            <div className="space-y-3">
                                {room.queue.map((song, index) => (
                                    <div
                                        key={song.id}
                                        className="relative overflow-hidden rounded-lg"
                                        onTouchStart={(e) => handleTouchStart(e, song.id)}
                                        onTouchMove={(e) => handleTouchMove(e, song.id)}
                                        onTouchEnd={() => handleTouchEnd(song.id)}
                                        onMouseDown={(e) => handleMouseDown(e, song.id)}
                                        onMouseMove={(e) => handleMouseMove(e, song.id)}
                                        onMouseUp={handleMouseUp}
                                        onMouseLeave={handleMouseLeave}
                                    >
                                        {/* Main song info container */}
                                        <div
                                            className={`flex items-center gap-x-2 p-3 bg-white/5 rounded-lg transition-transform duration-300 ease-in-out ${
                                                swipedSongId === song.id ? "-translate-x-[60px]" : "translate-x-0"
                                            }`}
                                        >
                                            <div
                                                className="text-white/60 text-sm font-mono w-2.5 flex-shrink-0">{index + 1}</div>
                                            {song.thumbnail && (
                                                <img
                                                    src={song.thumbnail || "/placeholder.svg"}
                                                    alt={song.title}
                                                    className="w-12 h-12 rounded object-cover flex-shrink-0"
                                                />
                                            )}
                                            <div className="flex-1 min-w-0">
                                                <p className="text-white font-medium truncate">{song.title}</p>
                                                <div className="flex items-center gap-x-1 text-white/60 text-sm">
                                                    <span>{formatTime(song.duration)}</span>
                                                    <span>•</span>
                                                    <span>{song.requester_name}</span>
                                                </div>
                                            </div>
                                            {/* Bring to Top Button */}
                                            {index !== 0 && ( // Only show if not the first song
                                                <Button
                                                    onClick={(e) => {
                                                        e.stopPropagation() // Prevent swipe interaction
                                                        bringSongToTop(song.id)
                                                    }}
                                                    size="sm"
                                                    variant="ghost"
                                                    className="text-white/60 hover:text-blue-400 hover:bg-blue-500/20 flex-shrink-0 w-7 h-7 p-0"
                                                    aria-label="Bring song to top"
                                                >
                                                    <ArrowUpNarrowWide className="h-4 w-4" strokeWidth={2}/>
                                                </Button>
                                            )}
                                        </div>

                                        {/* Delete button revealed on swipe */}
                                        <div
                                            className={`absolute inset-y-0 right-0 flex items-center justify-center bg-red-600 rounded-lg transition-transform duration-300 ease-in-out ${
                                                swipedSongId === song.id ? "translate-x-0" : "translate-x-full"
                                            }`}
                                            style={{width: "60px"}} // Smaller width for the delete area
                                        >
                                            <Button
                                                onClick={(e) => {
                                                    e.stopPropagation() // Prevent swipe interaction
                                                    removeSong(song.id)
                                                }}
                                                size="icon"
                                                variant="ghost"
                                                className="text-white hover:bg-red-700"
                                                aria-label="Delete song"
                                            >
                                                <Trash2 className="h-5 w-5" strokeWidth={2}/>
                                            </Button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div className="text-center text-white/60 py-4">
                                <p>播放清單是空的</p>
                                <p className="text-sm mt-1">使用 LINE Bot 新增歌曲</p>
                            </div>
                        )}
                    </CardContent>
                </Card>

                {/* Members */}
                <Card className="bg-white/10 backdrop-blur-sm border-white/20">
                    <CardContent className="p-4">
                        <h3 className="text-white font-semibold mb-4 flex items-center">
                            <Users className="h-4 w-4 mr-2" strokeWidth={2}/>
                            房間成員 ({room.members.length})
                        </h3>

                        <div className="space-y-2">
                            {room.members.map((member) => (
                                <div key={member.user_id}
                                     className="flex items-center space-x-3 p-2 bg-white/5 rounded">
                                    <User className="h-4 w-4 text-white/60" strokeWidth={2}/>
                                    <span className="text-white">{member.user_name}</span>
                                    {member.user_id === userId && (
                                        <Badge variant="secondary" className="bg-white/20 text-white text-xs">
                                            您
                                        </Badge>
                                    )}
                                </div>
                            ))}
                        </div>
                    </CardContent>
                </Card>
            </div>
        </div>
    )
}

"use client"

import {useEffect, useState, useRef, useCallback} from "react"
import {useParams, useSearchParams, useRouter} from "next/navigation"
import {Card, CardContent} from "@/components/ui/card"
import {AlertCircle, Check, Music} from "lucide-react"
import {useWebSocket} from "@/hooks/use-websocket"
import {useStatusMessage} from "@/hooks/use-status-message"
import {API_ENDPOINTS, LINE_CONFIG} from "@/lib/config"
import {loadAudio} from "@/lib/audio-loader"
import {RoomHeader} from "@/components/room/room-header"
import {NowPlaying} from "@/components/room/now-playing"
import {QuickPlayGrid} from "@/components/room/quick-play-grid"
import {QueueList} from "@/components/room/queue-list"
import {MemberList} from "@/components/room/member-list"
import {MessageModal, RefreshModal} from "@/components/room/room-modals"
import type {QuickPlaySong, Room} from "@/types/room"

export default function RoomPage() {
    const params = useParams()
    const searchParams = useSearchParams()
    const router = useRouter()
    const roomId = params.roomId as string
    const userId = searchParams.get("userId") || ""

    const [room, setRoom] = useState<Room | null>(null)
    const [currentTime, setCurrentTime] = useState(0)
    const [isLoading, setIsLoading] = useState(true)
    const [audioLoading, setAudioLoading] = useState(false)
    const [audioError, setAudioError] = useState<string | null>(null)
    const [songDownloading, setSongDownloading] = useState(false)
    const [hasUserInteractedWithPlayButton, setHasUserInteractedWithPlayButton] = useState(false)
    const [autoplayEnabled, setAutoplayEnabled] = useState(false)

    // Quick Play state
    const [quickPlaySongs, setQuickPlaySongs] = useState<QuickPlaySong[]>([])
    const [quickPlayLoading, setQuickPlayLoading] = useState(false)
    const [quickPlayAdding, setQuickPlayAdding] = useState<string | null>(null)
    const quickPlayInProgressRef = useRef<boolean>(false)

    const handleErrorModalClose = () => {
        setShowErrorModal(false)
        router.push("/")
    }
    const [showErrorModal, setShowErrorModal] = useState(false)
    const [errorMessage, setErrorMessage] = useState("")
    const [modalButtonText, setModalButtonText] = useState("確認");
    const [modalAction, setModalAction] = useState<() => void>(() => handleErrorModalClose);

    const [isMuted, setIsMuted] = useState(false)
    const {message: statusMessage, opacity: statusMessageOpacity, showMessage} = useStatusMessage()

    const audioRef = useRef<HTMLAudioElement>(null)
    const silentAudioRef = useRef<HTMLAudioElement>(null)
    const [isPlayingSilentAudio, setIsPlayingSilentAudio] = useState(false)
    const progressIntervalRef = useRef<NodeJS.Timeout | null>(null)
    const audioLoaderCleanupRef = useRef<(() => void) | null>(null)
    // Set right before we pause or reload the audio ourselves, so the 'pause' event
    // handler can tell our own pauses apart from pauses made by the system
    const expectedPauseRef = useRef(false)

    // Refs to hold the latest state values for stable callbacks
    const roomRef = useRef<Room | null>(null)
    const audioErrorRef = useRef<string | null>(null)
    const songDownloadingRef = useRef<boolean>(false)
    const hasUserInteractedWithPlayButtonRef = useRef<boolean>(false)

    // State for audio status checking
    const [audioStatusChecking, setAudioStatusChecking] = useState<Set<string>>(new Set())
    const audioStatusCheckingRef = useRef<Set<string>>(new Set())
    const statusCheckIntervalsRef = useRef<Map<string, NodeJS.Timeout>>(new Map())
    const [audioRetryAttempts, setAudioRetryAttempts] = useState(0)
    const [audioInitialized, setAudioInitialized] = useState(false)
    const [showRefreshModal, setShowRefreshModal] = useState(false)
    const [isNewUserLoadingAudio, setIsNewUserLoadingAudio] = useState(false)
    const newUserLoadingTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const NEW_USER_LOADING_TIMEOUT = 5000 // 5 seconds
    const MAX_RETRY_ATTEMPTS = 2
    const [isPlaybackRequestPending, setIsPlaybackRequestPending] = useState(false);

    const handleShare = () => {
        const liffUrl = `https://liff.line.me/${LINE_CONFIG.LIFF_ID}?roomId=${roomId}`;
        window.open(liffUrl, "_blank");
    }

    // Fetch quick play songs when room is empty
    const fetchQuickPlaySongs = useCallback(async () => {
        if (quickPlaySongs.length > 0) return // Already have songs

        setQuickPlayLoading(true)
        try {
            const response = await fetch(API_ENDPOINTS.QUICK_PLAY(roomId))
            if (response.ok) {
                const data = await response.json()
                setQuickPlaySongs(data.songs || [])
            }
        } catch (error) {
            console.error("Failed to fetch quick play songs:", error)
        } finally {
            setQuickPlayLoading(false)
        }
    }, [roomId, quickPlaySongs.length])

    // Add quick play song to queue
    const addQuickPlaySong = async (song: QuickPlaySong) => {
        if (quickPlayAdding) return // Already adding a song

        setQuickPlayAdding(song.id)
        setHasUserInteractedWithPlayButton(true)
        hasUserInteractedWithPlayButtonRef.current = true
        quickPlayInProgressRef.current = true  // Mark quick play in progress

        try {
            const userName = room?.members.find(m => m.user_id === userId)?.user_name || "User"

            const response = await fetch(
                `${API_ENDPOINTS.ADD_SONG(roomId)}?user_id=${encodeURIComponent(userId)}&user_name=${encodeURIComponent(userName)}`,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        video_id: song.id,
                        title: song.title,
                        channel: song.channel,
                        duration: song.duration,
                        thumbnail: song.thumbnail
                    })
                }
            )

            if (!response.ok) {
                throw new Error("Failed to add song")
            }

            // Song will be added via WebSocket, clear quick play songs to show player
            setQuickPlaySongs([])
        } catch (error) {
            console.error("Failed to add quick play song:", error)
            setAudioError("新增歌曲失敗，請重試")
            quickPlayInProgressRef.current = false  // Clear on error
        } finally {
            setQuickPlayAdding(null)
        }
    }

    useEffect(() => {
        roomRef.current = room
        audioErrorRef.current = audioError
        songDownloadingRef.current = songDownloading

        // Fetch quick play songs when room has no current song and no queue
        if (room && !room.current_song && room.queue.length === 0 && quickPlaySongs.length === 0 && !quickPlayLoading) {
            fetchQuickPlaySongs()
        }
    }, [room, audioError, songDownloading, fetchQuickPlaySongs, quickPlaySongs.length, quickPlayLoading])

    useEffect(() => {
        hasUserInteractedWithPlayButtonRef.current = hasUserInteractedWithPlayButton
    }, [hasUserInteractedWithPlayButton])

    useEffect(() => {
        // Reset retry attempts when audio is successfully playing
        if (room?.playback_state.is_playing && !audioError && audioRef.current && !audioRef.current.paused) {
            setAudioRetryAttempts(0)
        }
    }, [room?.playback_state.is_playing, audioError])

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            // Clear all status check intervals
            statusCheckIntervalsRef.current.forEach(interval => clearInterval(interval))
            statusCheckIntervalsRef.current.clear()

            // Clear new user loading timeout
            if (newUserLoadingTimeoutRef.current) {
                clearTimeout(newUserLoadingTimeoutRef.current)
            }
        }
    }, [])

    useEffect(() => {
        // Check if the Media Session API is supported by the browser
        if (!('mediaSession' in navigator)) {
            return;
        }

        const {current_song} = room ?? {};

        if (current_song) {
            navigator.mediaSession.metadata = new MediaMetadata({
                title: current_song.title,
                artist: 'CarTunes｜播歌吧',
                album: current_song.channel,
                artwork: [
                    {
                        src: current_song.thumbnail || "/placeholder.jpg",
                        type: 'image/jpeg',
                    },
                ],
            });
        } else {
            // Clear metadata when no song is playing
            navigator.mediaSession.metadata = null;
        }
    }, [room?.current_song]);

    // This useEffect handles the media control buttons from the device's native UI
    useEffect(() => {
        if (!('mediaSession' in navigator)) {
            return;
        }
        if (!isConnected) {
            return;
        }

        // --- Play Action ---
        navigator.mediaSession.setActionHandler('play', () => {
            setHasUserInteractedWithPlayButton(true);
            togglePlayback(); // Just call the function
        });

        // --- Pause Action ---
        navigator.mediaSession.setActionHandler('pause', () => {
            togglePlayback(); // Just call the function
        });

        // --- Next Track Button ---
        if (room && (room.queue.length > 0 || room.autoplay)) {
            navigator.mediaSession.setActionHandler('nexttrack', () => {
                skipToNext();
            });
        } else {
            navigator.mediaSession.setActionHandler('nexttrack', null);
        }

        // --- Previous Track Button (Not implemented) ---
        navigator.mediaSession.setActionHandler('previoustrack', null);

    }, [room, togglePlayback, skipToNext]);

    // This useEffect updates the mobile local control panel playback state
    useEffect(() => {
        if (!('mediaSession' in navigator)) return;

        if (isPlaybackRequestPending) {
            // While a request is in flight, the state is indeterminate.
            navigator.mediaSession.playbackState = 'none';
        } else if (isPlayingSilentAudio) {
            // When playing silent audio, force the playback state to paused
            navigator.mediaSession.playbackState = 'paused';
        } else {
            // Normal operation - sync with the room, but show paused if this device isn't playing along
            // (e.g. it got paused by disconnecting from CarPlay), so the lock screen offers play
            navigator.mediaSession.playbackState =
                room?.playback_state.is_playing && hasUserInteractedWithPlayButton ? 'playing' : 'paused';
        }
    }, [room?.playback_state.is_playing, hasUserInteractedWithPlayButton, isPlaybackRequestPending, isPlayingSilentAudio]);

    useEffect(() => {
        if (silentAudioRef.current) {
            // Set attributes to prevent media session detection
            silentAudioRef.current.disableRemotePlayback = true;
            silentAudioRef.current.volume = 0;
            silentAudioRef.current.muted = true;

            // Try to remove it from media session consideration
            if ('mediaSession' in navigator) {
                // Some browsers respect this attribute
                (silentAudioRef.current as any).mediaGroup = 'silent';
            }
        }
    }, []);

    // Loop local audio while repeat is enabled, so the song restarts seamlessly
    useEffect(() => {
        if (audioRef.current) {
            audioRef.current.loop = room?.repeat ?? false
        }
    }, [room?.repeat])

    // Callbacks for audio-loader, made stable by not depending on 'room' directly
    const handleLoadedMetadata = useCallback((audioElement: HTMLAudioElement, initialTime: number) => {
        // If initialTime is negative (loading state), don't set audio currentTime yet
        // Let the audio element stay at 0 until backend sends positive time
        if (initialTime >= 0) {
            audioElement.currentTime = initialTime
            console.log(`Setting audio currentTime to ${initialTime}`)
        } else {
            console.log(`Backend in loading state (${initialTime}), keeping audio at 0 until ready`)
            // Audio element will naturally start at 0, which is what we want during loading
        }
    }, [])

    const handleCanPlay = useCallback(
        async (audioElement: HTMLAudioElement, isPlaying: boolean, userHasInteracted: boolean) => {
            setIsNewUserLoadingAudio(false)

            // Clear the timeout if audio loads successfully
            if (newUserLoadingTimeoutRef.current) {
                clearTimeout(newUserLoadingTimeoutRef.current)
                newUserLoadingTimeoutRef.current = null
            }

            // Check if this was a quick play - auto-start playback
            if (quickPlayInProgressRef.current) {
                quickPlayInProgressRef.current = false  // Clear the flag

                // Automatically trigger play by calling the backend
                try {
                    const response = await fetch(`${API_ENDPOINTS.PLAYBACK(roomId)}?user_id=${userId}`, {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({is_playing: true, current_time: 0})
                    })
                    if (response.ok) {
                        // Backend will broadcast PLAYBACK_STARTED, which will trigger audio.play()
                        console.log("Quick play: auto-started playback")
                    }
                } catch (error) {
                    console.error("Quick play: failed to auto-start:", error)
                }
                return
            }

            if (userHasInteracted && isPlaying && audioElement.paused) {
                audioElement.play().catch((e) => console.error("Autoplay blocked on canplay:", e))
            }
        },
        [roomId, userId]
    )

    // Pause local audio on purpose (e.g. backend asked to pause)
    const pauseLocalAudio = useCallback(() => {
        const audio = audioRef.current
        if (!audio || audio.paused) return
        expectedPauseRef.current = true
        audio.pause()
    }, [])

    // Handle pauses we didn't make, e.g. the phone disconnected from CarPlay/Bluetooth.
    // The system pauses the audio element then, so stop auto-resuming on this device
    // until the user presses play again. The room itself keeps playing for others.
    const handleAudioPause = useCallback(() => {
        const audio = audioRef.current
        if (expectedPauseRef.current) {
            expectedPauseRef.current = false
            return
        }
        if (!audio || audio.ended) return // Song finished naturally
        if (!hasUserInteractedWithPlayButtonRef.current) return

        console.log("Audio paused by the system (audio output disconnected?), stop auto-resuming")
        hasUserInteractedWithPlayButtonRef.current = false
        setHasUserInteractedWithPlayButton(false)
    }, [])

    const loadAudioForCurrentSong = useCallback(
        async (videoId: string, initialTime: number, isPlaying: boolean, userHasInteracted: boolean) => {
            if (audioLoaderCleanupRef.current) {
                audioLoaderCleanupRef.current()
                audioLoaderCleanupRef.current = null
            }

            if (audioRef.current) {
                // Loading a new source fires 'pause' if the audio is playing
                if (!audioRef.current.paused) {
                    expectedPauseRef.current = true
                }
                setAudioInitialized(true)
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

    const retryAudioPlayback = useCallback(async () => {
        setIsNewUserLoadingAudio(false)
        if (!room?.current_song || !audioRef.current) return false

        const currentAttempts = audioRetryAttempts + 1
        setAudioRetryAttempts(currentAttempts)

        console.log(`Attempting audio retry ${currentAttempts}/${MAX_RETRY_ATTEMPTS}`)

        try {
            // Clear previous error
            setAudioError(null)

            // Reload the audio completely
            if (audioLoaderCleanupRef.current) {
                audioLoaderCleanupRef.current()
                audioLoaderCleanupRef.current = null
            }

            // Get fresh room state for accurate timing
            const response = await fetch(`${API_ENDPOINTS.ROOM(roomId)}`)
            const freshRoomData = await response.json()
            const currentTime = Math.max(0, freshRoomData.playback_state.current_time)

            // Reload audio from scratch
            await loadAudioForCurrentSong(
                room.current_song.video_id,
                currentTime,
                freshRoomData.playback_state.is_playing,
                hasUserInteractedWithPlayButtonRef.current
            )

            // Wait a moment for audio to load
            await new Promise(resolve => setTimeout(resolve, 1000))

            // Try to play if room is playing
            if (freshRoomData.playback_state.is_playing && hasUserInteractedWithPlayButtonRef.current) {
                if (currentTime >= 0) {
                    audioRef.current.currentTime = currentTime
                }
                await audioRef.current.play()
                console.log(`Audio retry ${currentAttempts} successful`)
                setAudioRetryAttempts(0) // Reset on success
                return true
            }

            return true
        } catch (error) {
            console.error(`Audio retry ${currentAttempts} failed:`, error)

            if (currentAttempts >= MAX_RETRY_ATTEMPTS) {
                console.log('Max retry attempts reached, showing refresh modal')
                setShowRefreshModal(true)
                return false
            } else {
                // Try again after a delay
                setTimeout(() => retryAudioPlayback(), 2000)
                return false
            }
        }
    }, [audioRetryAttempts, room, roomId, hasUserInteractedWithPlayButtonRef, loadAudioForCurrentSong])

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
                        autoplay: roomData.autoplay,
                        repeat: roomData.repeat ?? false,
                    }))
                    setAutoplayEnabled(roomData.autoplay)

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
                        ).catch(error => {
                            console.error("Audio loading failed:", error)
                            setAudioError("載入失敗，正在重試...")
                            retryAudioPlayback()
                        })

                        // START STATUS CHECK IMMEDIATELY when new song appears
                        console.log("New song detected, starting status check")
                        checkAudioStatus(data.data.current_song.video_id)

                    } else if (!data.data.current_song && audioRef.current) {
                        // Pause and clear audio when no current song
                        pauseLocalAudio()
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
                        }
                    })
                    break

                case "QUEUE_BATCH_ADDED":
                    setRoom((prev) => {
                        if (!prev) return null

                        // Add all songs from batch to the queue at once
                        return {
                            ...prev,
                            queue: [...prev.queue, ...data.data.songs],
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
                                if (
                                    newCurrentTime !== undefined &&
                                    newCurrentTime >= 0 &&
                                    Math.abs(audioRef.current.currentTime - newCurrentTime) > 2
                                ) {
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
                            pauseLocalAudio()
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
                                autoplay: data.data.autoplay,
                            }
                            : null,
                    )
                    setAutoplayEnabled(data.data.autoplay)
                    break

                case "REPEAT_CHANGED":
                    setRoom((prev) => (prev ? {...prev, repeat: data.data.repeat} : null))
                    break

                case "PLAYBACK_STARTED":
                    setRoom((prev) =>
                        prev
                            ? {
                                ...prev,
                                playback_state: {
                                    ...prev.playback_state,
                                    is_playing: true,
                                    current_time: data.data.current_time ?? prev.playback_state.current_time,
                                },
                            }
                            : null,
                    )
                    if (data.data.current_time !== undefined && data.data.current_time !== null) {
                        setCurrentTime(Math.max(0, data.data.current_time))
                    }
                    // Handle audio playback - check if audio is ready first
                    if (audioRef.current && currentUserInteracted) {
                        if (data.data.current_time !== undefined && data.data.current_time >= 0) {
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
                                    current_time:
                                        data.data.current_time !== undefined ? data.data.current_time : prev.playback_state.current_time,
                                },
                            }
                            : null,
                    )
                    // Handle audio pause
                    if (audioRef.current) {
                        pauseLocalAudio()
                        if (
                            data.data.current_time !== undefined &&
                            Math.abs(audioRef.current.currentTime - data.data.current_time) > 2
                        ) {
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

                        if (
                            !isActuallyPlaying &&
                            currentUserInteracted &&
                            roomRef.current?.playback_state.is_playing &&
                            !songDownloading
                        ) {
                            console.log("Audio should be playing but isn't - starting")
                            audioRef.current.currentTime = progressTime
                            audioRef.current.play().catch(e => console.log("Failed to start stalled audio:", e))
                        } else if (isActuallyPlaying && Math.abs(audioRef.current.currentTime - progressTime) > 2) {
                            console.log(`Resyncing playing audio: local ${audioRef.current.currentTime.toFixed(2)}, remote ${progressTime.toFixed(2)}`)
                            audioRef.current.currentTime = progressTime + 1
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
        [loadAudioForCurrentSong, pauseLocalAudio, setErrorMessage, setShowErrorModal],
    )

    const checkAudioStatus = useCallback(async (videoId: string) => {
        if (audioStatusCheckingRef.current.has(videoId)) {
            return // Already checking this video
        }

        console.log(`Starting status check for ${videoId} in room ${roomId}`)

        audioStatusCheckingRef.current.add(videoId)
        setAudioStatusChecking(prev => new Set([...prev, videoId]))

        let retryCount = 0
        let timeoutHandle: NodeJS.Timeout | null = null
        let isDownloading = false

        const cleanup = () => {
            // Clear interval and tracking
            const interval = statusCheckIntervalsRef.current.get(videoId)
            if (interval) {
                clearInterval(interval)
                statusCheckIntervalsRef.current.delete(videoId)
            }

            if (timeoutHandle) {
                clearTimeout(timeoutHandle)
            }

            audioStatusCheckingRef.current.delete(videoId)
            setAudioStatusChecking(prev => {
                const newSet = new Set(prev)
                newSet.delete(videoId)
                return newSet
            })
        }

        const checkStatus = async () => {
            try {
                const url = `${API_ENDPOINTS.AUDIO_STATUS(videoId, roomId)}`
                console.log(`Checking status at: ${url}`)

                const response = await fetch(url)
                console.log(`Status response:`, response.status, response.ok)

                if (response.ok) {
                    const data = await response.json()
                    console.log(`Status data:`, data)

                    if (data.status === "downloading") {
                        isDownloading = true
                        setSongDownloading(true)
                        setAudioLoading(false)
                        setAudioError(null)
                        // Reset retry count when downloading
                        retryCount = 0
                        // Cancel timeout since backend is actively downloading
                        if (timeoutHandle) {
                            clearTimeout(timeoutHandle)
                            timeoutHandle = null
                        }
                        return false
                    } else if (data.status === "ready") {
                        // Audio is ready - IMMEDIATELY clear checking state
                        console.log(`✅ Audio ready for ${videoId}, clearing status check`)

                        cleanup()
                        setSongDownloading(false)

                        // If audio is ready and we were waiting as a new user, load it
                        if (isNewUserLoadingAudio && room?.current_song?.video_id === videoId) {
                            console.log("Audio ready for new user, loading audio")
                            await loadAudioForCurrentSong(
                                videoId,
                                Math.max(0, room.playback_state.current_time),
                                room.playback_state.is_playing,
                                hasUserInteractedWithPlayButtonRef.current
                            )
                        }

                        return true
                    } else {
                        // Status is not ready/downloading (404 or other error)
                        if (!isDownloading) {
                            retryCount++
                            if (retryCount >= MAX_RETRY_ATTEMPTS) {
                                cleanup()
                                setAudioError("音訊無法載入，請直接跳至下一首")
                                setSongDownloading(false)
                                return false
                            }
                        }
                        return false
                    }
                } else {
                    // Request failed (404 or network error)
                    if (!isDownloading) {
                        retryCount++
                        if (retryCount >= MAX_RETRY_ATTEMPTS) {
                            cleanup()
                            setAudioError("音訊無法載入，請直接跳至下一首")
                            setSongDownloading(false)
                            return false
                        }
                    }
                    return false
                }
            } catch (error) {
                console.error("Status check error:", error)
                if (!isDownloading) {
                    retryCount++
                    if (retryCount >= MAX_RETRY_ATTEMPTS) {
                        cleanup()
                        setAudioError("音訊無法載入，請直接跳至下一首")
                        setSongDownloading(false)
                        return false
                    }
                }
                return false
            }
        }

        // Only set timeout if not downloading
        if (!isDownloading) {
            timeoutHandle = setTimeout(() => {
                if (!isDownloading) {
                    console.log(`Audio status check timeout after ${NEW_USER_LOADING_TIMEOUT}ms`)
                    cleanup()
                    setAudioError("音訊無法載入，請直接跳至下一首")
                    setSongDownloading(false)
                }
            }, NEW_USER_LOADING_TIMEOUT)
        }

        // Initial check
        const isReady = await checkStatus()

        if (!isReady && (isDownloading || retryCount < MAX_RETRY_ATTEMPTS)) {
            // Set up periodic checking
            const interval = setInterval(async () => {
                const ready = await checkStatus()
                if (ready || (!isDownloading && retryCount >= MAX_RETRY_ATTEMPTS)) {
                    clearInterval(interval)
                    statusCheckIntervalsRef.current.delete(videoId)
                }
            }, 2000) // Check every 2 seconds

            statusCheckIntervalsRef.current.set(videoId, interval)
        }
    }, [roomId, setSongDownloading, setAudioLoading, setAudioError, isNewUserLoadingAudio, room, loadAudioForCurrentSong])

    const {isConnected, connectionStatus, playSilentAudio, stopSilentAudio} = useWebSocket({
        url: `${API_ENDPOINTS.WEBSOCKET(roomId)}?user_id=${userId}`,
        onMessage: handleWebSocketMessage,
        onConnect: useCallback(() => {
            console.log("WebSocket connected successfully")
        }, []),
        onDisconnect: useCallback(() => {
            console.log("WebSocket disconnected")
        }, []),
        onConnectionFailed: useCallback(() => {
            setErrorMessage("連線失敗！\n點擊下方按鈕重新整理")
            setModalButtonText("重新載入頁面")
            setModalAction(() => () => window.location.reload())
            setShowErrorModal(true)
        }, [setErrorMessage, setModalButtonText, setModalAction, setShowErrorModal]),
        enabled: !isLoading && room !== null,
        reconnectInterval: 2000,
        maxReconnectAttempts: 3,
        silentAudioRef,
        onSilentAudioStateChange: setIsPlayingSilentAudio,
    })

    // Play silent audio during loading states if user has interacted
    useEffect(() => {
        if ((songDownloading || audioLoading) && hasUserInteractedWithPlayButton && playSilentAudio) {
            console.log("Starting silent audio during loading state")
            playSilentAudio()
        } else if (!(songDownloading || audioLoading) && stopSilentAudio) {
            console.log("Stopping silent audio after loading")
            stopSilentAudio()
        }
    }, [songDownloading, audioLoading, hasUserInteractedWithPlayButton, playSilentAudio, stopSilentAudio])

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

    useEffect(() => {
        // Clear new user loading state when user has interacted
        if (hasUserInteractedWithPlayButton) {
            setIsNewUserLoadingAudio(false)
        }
    }, [hasUserInteractedWithPlayButton])

    async function checkRoomExists() {
        try {
            const response = await fetch(API_ENDPOINTS.ROOM(roomId))
            if (!response.ok) {
                setErrorMessage("不存在的房間")
                setModalButtonText("返回首頁")
                setModalAction(() => () => window.location.href = "/")
                setShowErrorModal(true)
                setIsLoading(false)
                return
            }

            const roomData = await response.json()
            setRoom(roomData)
            setCurrentTime(roomData.playback_state.current_time || 0)
            setIsLoading(false)
            setAutoplayEnabled(roomData.autoplay)

            if (roomData.current_song) {
                const isNewUserJoiningActiveRoom = roomData.playback_state.is_playing && !hasUserInteractedWithPlayButtonRef.current

                if (isNewUserJoiningActiveRoom) {
                    setIsNewUserLoadingAudio(true)
                    console.log("New user joining active room - starting audio load")

                    // Set timeout for new user loading
                    newUserLoadingTimeoutRef.current = setTimeout(() => {
                        if (isNewUserLoadingAudio) {
                            console.log("New user loading timeout reached")
                            setIsNewUserLoadingAudio(false)
                            setAudioError("載入超時，請重試")
                            retryAudioPlayback()
                        }
                    }, NEW_USER_LOADING_TIMEOUT)
                }

                console.log("Checking audio status for current song")
                await checkAudioStatus(roomData.current_song.video_id)

                await loadAudioForCurrentSong(
                    roomData.current_song.video_id,
                    Math.max(0, roomData.playback_state.current_time),
                    roomData.playback_state.is_playing,
                    hasUserInteractedWithPlayButtonRef.current,
                )
            }
        } catch (err) {
            setErrorMessage("連線失敗，請檢查網路連線後重新整理頁面")
            setModalButtonText("重新載入頁面")
            setModalAction(() => () => window.location.reload())
            setShowErrorModal(true)
            setIsLoading(false)
        }
    }

    async function togglePlayback() {
        // Guard against spam clicks and invalid states like downloading or no song.
        if (isPlaybackRequestPending || !room?.current_song || songDownloading) {
            return;
        }

        const audioEl = audioRef.current;
        if (!audioEl) return;

        // Set a flag to prevent further clicks until this operation is complete.
        setIsPlaybackRequestPending(true);

        // This ensures the first click on a device correctly enables audio playback.
        if (!hasUserInteractedWithPlayButtonRef.current) {
            setHasUserInteractedWithPlayButton(true);
            hasUserInteractedWithPlayButtonRef.current = true;
        }

        try {
            // Scenario 1: The room is already playing, but our local audio is paused.
            // This is a common case for new users due to browser autoplay policies.
            // We just need to play the audio locally to sync up. No backend call is needed.
            if (room.playback_state.is_playing && audioEl.paused) {
                console.log("Local audio is paused while room is playing. Syncing now.");
                // To be safe, let's fetch the latest room state to get the most accurate time.
                const response = await fetch(API_ENDPOINTS.ROOM(roomId));
                if (!response.ok) throw new Error("Could not fetch room state to sync audio.");

                const latestRoomData = await response.json();
                const latestCurrentTime = latestRoomData.playback_state.current_time;
                if (latestCurrentTime >= 0) {
                    audioEl.currentTime = latestCurrentTime;
                }
                await audioEl.play();
                setAudioError(null); // Clear any previous playback errors
                return; // Exit after successfully syncing the local player
            }

            // Scenario 2: This is a normal play/pause request.
            // We determine the desired new state and tell the backend.
            const desiredNewState = !room.playback_state.is_playing;
            console.log(`Requesting playback state change to: ${desiredNewState ? 'playing' : 'paused'}`);

            const response = await fetch(`${API_ENDPOINTS.PLAYBACK(roomId)}?user_id=${userId}`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    is_playing: desiredNewState,
                    current_time: audioEl.currentTime,
                }),
            });

            // The backend will now process this request. If successful, it will broadcast
            // the new state via WebSocket, and our WebSocket handler will update the audio.
            // We only need to check for errors here.

            if (response.status === 429) {
                console.warn("Playback command was throttled by the server. No change was made.");
                // No action needed. The UI already reflects the correct, unchanged state.
            } else if (!response.ok) {
                throw new Error("Failed to send playback command to the server.");
            }
        } catch (error) {
            console.error("Error in togglePlayback:", error);
            setAudioError("設定音訊狀態失敗！請再試一次");
        } finally {
            // IMPORTANT: Reset the pending flag after a 1-second cooldown.
            // This acts as a client-side throttle to prevent spamming the backend
            // and is the key to preventing the double-click issue.
            setTimeout(() => {
                setIsPlaybackRequestPending(false);
            }, 1000);
        }
    }

    async function skipToNext() {
        try {
            const response = await fetch(`${API_ENDPOINTS.SKIP_NEXT(roomId)}?user_id=${userId}`, {
                method: "POST"
            })
            if (response.status === 429) {
                console.log("Skipping song getting throttle blocked, ignoring")
                return
            }
        } catch (err) {
            console.error("Failed to skip song:", err)
        }
    }

    async function removeSong(songId: string) {
        try {
            await fetch(`${API_ENDPOINTS.REMOVE_SONG(roomId, songId)}?user_id=${userId}`, {
                method: "DELETE",
            })
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
            const response = await fetch(`${API_ENDPOINTS.REORDER_QUEUE(roomId)}?user_id=${userId}`, {
                method: "PUT",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({song_ids: newSongIds}),
            })

            const data = await response.json()

            if (data.message === "Queue reordered") {
                setRoom((prev) => (prev ? {...prev, queue: newQueue} : null))
            } else if (data.message === "Queue unchanged, blocked by throttle") {
                // Use a div with white-space pre-wrap for multiline messages
                setErrorMessage(
                    '<div style="white-space: pre-wrap;">嘿！慢下來\n插那麼多首歌可能會被討厭喔...</div>'
                );
                setModalButtonText("知道了");
                setModalAction(() => () => setShowErrorModal(false));
                setShowErrorModal(true);
            }
        } catch (err) {
            console.error("Failed to bring song to top:", err)
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


    const toggleMute = () => {
        if (audioRef.current) {
            const newState = !isMuted
            audioRef.current.muted = newState
            setIsMuted(newState)
            showMessage(
                newState ? "靜音本地播放" : "解除本地靜音",
                newState ? "text-red-500" : "text-green-400",
                {hidesMuteButton: true},
            )
        }
    }

    const handleAutoplayToggle = async () => {
        if (!roomId) return
        try {
            const response = await fetch(`${API_ENDPOINTS.ROOM(roomId)}/autoplay/toggle`, {
                method: "POST",
            })

            // Handle throttling - just do nothing
            if (response.status === 429) {
                console.log("Autoplay toggle throttled, ignoring")
                return
            }

            if (!response.ok) {
                throw new Error("Failed to toggle autoplay")
            }

            const data = await response.json()
            console.log("Autoplay toggled:", data.autoplay)

            // Update local state immediately with backend response
            setAutoplayEnabled(data.autoplay)
            setRoom((prev) =>
                prev
                    ? {
                        ...prev,
                        autoplay: data.autoplay,
                    }
                    : null
            )

        } catch (error) {
            console.error("Error toggling autoplay:", error)
            setErrorMessage("自動播放切換失敗")
            setShowErrorModal(true)
        }
    }

    const handleRepeatToggle = async () => {
        if (!roomId) return
        try {
            const response = await fetch(API_ENDPOINTS.TOGGLE_REPEAT(roomId), {
                method: "POST",
            })

            // Handle throttling - just do nothing
            if (response.status === 429) {
                console.log("Repeat toggle throttled, ignoring")
                return
            }

            if (!response.ok) {
                throw new Error("Failed to toggle repeat")
            }

            const data = await response.json()
            setRoom((prev) => (prev ? {...prev, repeat: data.repeat} : null))
        } catch (error) {
            console.error("Error toggling repeat:", error)
            setErrorMessage("重複播放切換失敗")
            setShowErrorModal(true)
        }
    }

    const copyRoomId = async () => {
        if (!roomId) return

        if (!navigator.clipboard) {
            showMessage("網頁不支援複製", "text-red-500", {icon: AlertCircle})
            return
        }
        try {
            await navigator.clipboard.writeText(roomId)
            showMessage("複製房間代碼", "text-green-400", {icon: Check})
        } catch (err) {
            console.error("Failed to copy room ID:", err)
            showMessage("複製失敗", "text-red-500", {icon: AlertCircle})
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

    if (!room) {
        return (
            <div className="min-h-screen bg-gradient-to-br from-purple-600 via-blue-600 to-cyan-600">
                <MessageModal
                    isOpen={showErrorModal}
                    message={errorMessage}
                    buttonText={modalButtonText}
                    onAction={modalAction}
                />
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-purple-600 via-blue-600 to-cyan-600">
            <audio ref={audioRef} preload="metadata" crossOrigin="anonymous" onPause={handleAudioPause}/>
            <audio
                ref={silentAudioRef}
                src="/soundless.mp3"
                preload="auto"
                loop
                playsInline
                // Add these attributes to prevent media session interference
                muted
                style={{display: 'none'}}
            />

            <MessageModal
                isOpen={showErrorModal}
                message={errorMessage}
                buttonText={modalButtonText}
                onAction={modalAction}
            />
            <RefreshModal isOpen={showRefreshModal} onClose={() => setShowRefreshModal(false)}/>

            <RoomHeader
                roomId={roomId}
                activeUsers={room.active_users}
                isConnected={isConnected}
                isMuted={isMuted}
                statusMessage={statusMessage}
                statusMessageOpacity={statusMessageOpacity}
                onCopyRoomId={copyRoomId}
                onShare={handleShare}
                onToggleMute={toggleMute}
            />

            <div
                className={`transition-all duration-300 ${!isConnected ? 'blur-sm pointer-events-none opacity-50' : ''}`}>
                <div className="max-w-md mx-auto p-4 space-y-4">
                    {/* Current Song */}
                    <Card className="bg-white/10 backdrop-blur-sm border-white/20">
                        <CardContent className="p-3 flex flex-col">
                            {room.current_song ? (
                                <NowPlaying
                                    song={room.current_song}
                                    currentTime={currentTime}
                                    isPlaying={room.playback_state.is_playing && hasUserInteractedWithPlayButton}
                                    canSkip={!(room.autoplay && !room.queue.length)}
                                    isRepeat={room.repeat}
                                    audioStatus={{
                                        songDownloading,
                                        audioLoading,
                                        audioError,
                                        isNewUserLoadingAudio,
                                        isCheckingStatus: audioStatusCheckingRef.current.has(room.current_song.video_id),
                                    }}
                                    onTogglePlayback={togglePlayback}
                                    onSkip={skipToNext}
                                    onToggleRepeat={handleRepeatToggle}
                                />
                            ) : (
                                <QuickPlayGrid
                                    songs={quickPlaySongs}
                                    isLoading={quickPlayLoading}
                                    addingSongId={quickPlayAdding}
                                    onSelect={addQuickPlaySong}
                                />
                            )}
                        </CardContent>
                    </Card>

                    <QueueList
                        queue={room.queue}
                        autoplay={room.autoplay}
                        onToggleAutoplay={handleAutoplayToggle}
                        onRemoveSong={removeSong}
                        onBringSongToTop={bringSongToTop}
                    />

                    <MemberList members={room.members} currentUserId={userId}/>
                </div>
            </div>
        </div>
    )
}

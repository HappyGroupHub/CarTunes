"use client"

import { useEffect, useState, useRef, useCallback } from "react" // Add useCallback
import { useParams, useSearchParams, useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { Play, Pause, SkipForward, Music, Clock, User, Users, Wifi, WifiOff, Trash2 } from "lucide-react"
import { useWebSocket } from "@/hooks/use-websocket"
import { formatTime } from "@/lib/utils"
import { Modal } from "@/components/ui/modal"
import { API_ENDPOINTS } from "@/lib/config"

interface Song {
  id: string
  video_id: string
  title: string
  artist?: string
  duration: number
  thumbnail?: string
  requested_by: string
  requested_by_name: string
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

  const audioRef = useRef<HTMLAudioElement>(null)
  const progressIntervalRef = useRef<NodeJS.Timeout | null>(null)

  // Check if room exists before connecting WebSocket
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
      setCurrentTime(roomData.playback_state.current_time || 0)
      setIsLoading(false)

      // Load current song audio
      if (roomData.current_song) {
        await loadAudio(roomData.current_song.video_id)
      }
    } catch (err) {
      setErrorMessage("不存在的房間")
      setShowErrorModal(true)
    }
  }

  const handleWebSocketMessage = useCallback(
    (data: any) => {
      // Wrap in useCallback
      console.log("WebSocket message:", data)

      switch (data.type) {
        case "ROOM_STATE":
          setRoom(data.data.room)
          break

        case "SONG_CHANGED":
          if (room) {
            setRoom((prev) =>
              prev
                ? {
                    ...prev,
                    current_song: data.data.current_song,
                  }
                : null,
            )

            // Load new audio
            if (data.data.current_song && audioRef.current) {
              loadAudio(data.data.current_song.video_id)
            }
          }
          break

        case "PLAYBACK_STARTED":
        case "PLAYBACK_PAUSED":
          if (room) {
            setRoom((prev) =>
              prev
                ? {
                    ...prev,
                    playback_state: {
                      ...prev.playback_state,
                      is_playing: data.data.is_playing,
                      current_time: data.data.current_time || prev.playback_state.current_time,
                    },
                  }
                : null,
            )

            // Sync audio playback
            if (audioRef.current) {
              if (data.data.is_playing) {
                audioRef.current.play()
              } else {
                audioRef.current.pause()
              }

              if (data.data.current_time !== undefined) {
                audioRef.current.currentTime = data.data.current_time
              }
            }
          }
          break

        case "PLAYBACK_PROGRESS":
          setCurrentTime(data.data.current_time)
          break

        case "SONG_ADDED":
          if (room) {
            setRoom((prev) =>
              prev
                ? {
                    ...prev,
                    queue: [...prev.queue, data.data.song],
                  }
                : null,
            )
          }
          break

        case "SONG_REMOVED":
          if (room) {
            setRoom((prev) =>
              prev
                ? {
                    ...prev,
                    queue: prev.queue.filter((song) => song.id !== data.data.song_id),
                  }
                : null,
            )
          }
          break

        case "QUEUE_REORDERED":
          if (room) {
            setRoom((prev) =>
              prev
                ? {
                    ...prev,
                    queue: data.data.queue,
                  }
                : null,
            )
          }
          break
      }
    },
    [room, audioRef],
  ) // Add room and audioRef to dependencies

  const { isConnected, connectionStatus } = useWebSocket({
    url: `${API_ENDPOINTS.WEBSOCKET(roomId)}?user_id=${userId}`,
    onMessage: handleWebSocketMessage,
    onConnect: useCallback(() => {
      // Wrap in useCallback
      console.log("WebSocket connected successfully")
    }, []), // Empty dependency array as it doesn't depend on props/state
    onDisconnect: useCallback(() => {
      // Wrap in useCallback
      console.log("WebSocket disconnected")
    }, []), // Empty dependency array
    onConnectionFailed: useCallback(() => {
      // Wrap in useCallback
      setErrorMessage("連線失敗，請檢查網路連線後重新整理頁面")
      setShowErrorModal(true)
    }, [setErrorMessage, setShowErrorModal]), // Dependencies for state setters
    enabled: !isLoading && room !== null,
    reconnectInterval: 2000,
    maxReconnectAttempts: 3,
  })

  async function loadAudio(videoId: string) {
    if (!audioRef.current) return

    try {
      audioRef.current.src = API_ENDPOINTS.AUDIO_STREAM(videoId)
      audioRef.current.load()
    } catch (err) {
      console.error("Failed to load audio:", err)
    }
  }

  async function togglePlayback() {
    if (!room?.current_song) return

    const newIsPlaying = !room.playback_state.is_playing
    const currentAudioTime = audioRef.current?.currentTime || currentTime

    try {
      await fetch(`${API_ENDPOINTS.PLAYBACK(roomId)}?user_id=${userId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          is_playing: newIsPlaying,
          current_time: currentAudioTime,
        }),
      })
    } catch (err) {
      console.error("Failed to toggle playback:", err)
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
    } catch (err) {
      console.error("Failed to remove song:", err)
    }
  }

  // Update progress from audio element
  useEffect(() => {
    if (room?.playback_state.is_playing && audioRef.current) {
      progressIntervalRef.current = setInterval(() => {
        if (audioRef.current) {
          setCurrentTime(audioRef.current.currentTime)
        }
      }, 1000)
    } else {
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current)
        progressIntervalRef.current = null
      }
    }

    return () => {
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current)
      }
    }
  }, [room?.playback_state.is_playing])

  const handleErrorModalClose = () => {
    setShowErrorModal(false)
    router.push("/")
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-purple-600 via-blue-600 to-cyan-600 flex items-center justify-center">
        <div className="text-white text-center">
          <Music className="h-12 w-12 mx-auto mb-4 animate-pulse" />
          <p>檢查房間中...</p>
        </div>
      </div>
    )
  }

  if (!room) return null

  const progress = room.current_song ? (currentTime / room.current_song.duration) * 100 : 0

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-600 via-blue-600 to-cyan-600">
      <audio ref={audioRef} preload="metadata" />

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
            <Music className="h-6 w-6 text-white" />
            <span className="text-white font-semibold">房間 {roomId}</span>
          </div>
          <div className="flex items-center space-x-2">
            {isConnected ? <Wifi className="h-4 w-4 text-green-400" /> : <WifiOff className="h-4 w-4 text-red-400" />}
            <Badge variant="secondary" className="bg-white/20 text-white">
              <Users className="h-3 w-3 mr-1" />
              {room.active_users}
            </Badge>
          </div>
        </div>
      </div>

      <div className="max-w-md mx-auto p-4 space-y-4">
        {/* Current Song */}
        <Card className="bg-white/10 backdrop-blur-sm border-white/20">
          <CardContent className="p-6">
            {room.current_song ? (
              <div className="space-y-4">
                {/* Song Info */}
                <div className="text-center">
                  {room.current_song.thumbnail && (
                    <img
                      src={room.current_song.thumbnail || "/placeholder.svg"}
                      alt={room.current_song.title}
                      className="w-32 h-32 mx-auto rounded-lg object-cover mb-4"
                    />
                  )}
                  <h2 className="text-white font-bold text-lg mb-1">{room.current_song.title}</h2>
                  {room.current_song.artist && <p className="text-white/70 mb-2">{room.current_song.artist}</p>}
                  <div className="flex items-center justify-center space-x-4 text-white/60 text-sm">
                    <div className="flex items-center">
                      <User className="h-3 w-3 mr-1" />
                      {room.current_song.requested_by_name}
                    </div>
                    <div className="flex items-center">
                      <Clock className="h-3 w-3 mr-1" />
                      {formatTime(room.current_song.duration)}
                    </div>
                  </div>
                </div>

                {/* Progress */}
                <div className="space-y-2">
                  <Progress value={progress} className="h-2" />
                  <div className="flex justify-between text-white/60 text-sm">
                    <span>{formatTime(Math.floor(currentTime))}</span>
                    <span>{formatTime(room.current_song.duration)}</span>
                  </div>
                </div>

                {/* Controls */}
                <div className="flex justify-center space-x-4">
                  <Button
                    onClick={togglePlayback}
                    size="lg"
                    className="bg-white/20 hover:bg-white/30 text-white rounded-full w-16 h-16"
                  >
                    {room.playback_state.is_playing ? <Pause className="h-8 w-8" /> : <Play className="h-8 w-8" />}
                  </Button>
                  <Button
                    onClick={skipToNext}
                    size="lg"
                    className="bg-white/20 hover:bg-white/30 text-white rounded-full w-16 h-16"
                  >
                    <SkipForward className="h-8 w-8" />
                  </Button>
                </div>
              </div>
            ) : (
              <div className="text-center text-white/60 py-8">
                <Music className="h-12 w-12 mx-auto mb-4 opacity-50" />
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
              <Music className="h-4 w-4 mr-2" />
              播放清單 ({room.queue.length})
            </h3>

            {room.queue.length > 0 ? (
              <div className="space-y-3">
                {room.queue.map((song, index) => (
                  <div key={song.id} className="flex items-center space-x-3 p-3 bg-white/5 rounded-lg">
                    <div className="text-white/60 text-sm font-mono w-6">{index + 1}</div>
                    {song.thumbnail && (
                      <img
                        src={song.thumbnail || "/placeholder.svg"}
                        alt={song.title}
                        className="w-12 h-12 rounded object-cover"
                      />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-white font-medium truncate">{song.title}</p>
                      <div className="flex items-center space-x-2 text-white/60 text-sm">
                        <span>{song.requested_by_name}</span>
                        <span>•</span>
                        <span>{formatTime(song.duration)}</span>
                      </div>
                    </div>
                    <Button
                      onClick={() => removeSong(song.id)}
                      size="sm"
                      variant="ghost"
                      className="text-white/60 hover:text-red-400 hover:bg-red-500/20"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
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
              <Users className="h-4 w-4 mr-2" />
              房間成員 ({room.members.length})
            </h3>

            <div className="space-y-2">
              {room.members.map((member) => (
                <div key={member.user_id} className="flex items-center space-x-3 p-2 bg-white/5 rounded">
                  <User className="h-4 w-4 text-white/60" />
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

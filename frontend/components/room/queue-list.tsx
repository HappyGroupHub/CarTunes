"use client"

import React, {useRef, useState} from "react"
import {Button} from "@/components/ui/button"
import {Card, CardContent} from "@/components/ui/card"
import {ArrowUpNarrowWide, Music, Trash2} from "lucide-react"
import {AutoplayToggle} from "@/components/autoplay-toggle"
import {formatTime} from "@/lib/utils"
import type {Song} from "@/types/room"

const SWIPE_THRESHOLD = 50 // Pixels to swipe to reveal delete button

interface QueueListProps {
    queue: Song[]
    autoplay: boolean
    onToggleAutoplay: () => void
    onRemoveSong: (songId: string) => void
    onBringSongToTop: (songId: string) => void
}

export function QueueList({queue, autoplay, onToggleAutoplay, onRemoveSong, onBringSongToTop}: QueueListProps) {
    // State for swipe-to-delete
    const [swipedSongId, setSwipedSongId] = useState<string | null>(null)
    const touchStartX = useRef(0)
    const touchCurrentX = useRef(0)

    const handleRemove = (songId: string) => {
        onRemoveSong(songId)
        setSwipedSongId(null) // Close swipe after deletion
    }

    // Swipe handlers
    const handleTouchStart = (e: React.TouchEvent) => {
        setSwipedSongId(null) // Close any currently swiped item
        touchStartX.current = e.touches[0].clientX
        touchCurrentX.current = e.touches[0].clientX
    }

    const handleTouchMove = (e: React.TouchEvent, songId: string) => {
        touchCurrentX.current = e.touches[0].clientX
        const deltaX = touchCurrentX.current - touchStartX.current

        if (deltaX < -SWIPE_THRESHOLD) {
            // Swiping left
            setSwipedSongId(songId)
        } else if (deltaX > SWIPE_THRESHOLD) {
            // Swiping right
            setSwipedSongId(null)
        }
    }

    const handleTouchEnd = () => {
        const deltaX = touchCurrentX.current - touchStartX.current
        if (Math.abs(deltaX) < SWIPE_THRESHOLD) {
            setSwipedSongId(null) // Close if not swiped enough
        }
        touchStartX.current = 0 // Reset for next interaction
        touchCurrentX.current = 0 // Reset currentX as well
    }

    // Mouse handlers for desktop (simulating touch)
    const handleMouseDown = (e: React.MouseEvent) => {
        setSwipedSongId(null) // Close any currently swiped item
        touchStartX.current = e.clientX
        touchCurrentX.current = e.clientX
    }

    const handleMouseMove = (e: React.MouseEvent, songId: string) => {
        if (touchStartX.current !== 0) {
            // Only if drag started
            touchCurrentX.current = e.clientX
            const deltaX = touchCurrentX.current - touchStartX.current
            if (deltaX < -SWIPE_THRESHOLD) {
                setSwipedSongId(songId)
            } else if (deltaX > SWIPE_THRESHOLD) {
                setSwipedSongId(null)
            }
        }
    }

    const handleMouseUp = () => {
        if (touchStartX.current !== 0) {
            const deltaX = touchCurrentX.current - touchStartX.current
            if (Math.abs(deltaX) < SWIPE_THRESHOLD) {
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

    return (
        <Card className="bg-white/10 backdrop-blur-sm border-white/20">
            <CardContent className="p-4">
                <h3 className="text-white font-semibold mb-4 flex items-center justify-between">
                    <div className="flex items-center">
                        <Music className="h-4 w-4 mr-2" strokeWidth={2}/>
                        播放清單 ({queue.length})
                    </div>
                    <div className="flex items-center space-x-2">
                        <span className="text-xs text-white/70">自動播放</span>
                        <AutoplayToggle isEnabled={autoplay} onToggle={onToggleAutoplay}/>
                    </div>
                </h3>

                {queue.length > 0 ? (
                    <div className="space-y-3">
                        {queue.map((song, index) => (
                            <div
                                key={song.id}
                                className="relative overflow-hidden rounded-lg"
                                onTouchStart={handleTouchStart}
                                onTouchMove={(e) => handleTouchMove(e, song.id)}
                                onTouchEnd={handleTouchEnd}
                                onMouseDown={handleMouseDown}
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
                                            src={song.thumbnail || "/placeholder.jpg"}
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
                                                onBringSongToTop(song.id)
                                            }}
                                            size="sm"
                                            variant="ghost"
                                            className="text-white/60 active:text-blue-400 active:bg-blue-500/20 md:hover:text-blue-400 md:hover:bg-blue-500/20 flex-shrink-0 w-7 h-7 p-0"
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
                                            handleRemove(song.id)
                                        }}
                                        size="icon"
                                        variant="ghost"
                                        className="text-white active:bg-red-700 md:hover:bg-red-700"
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
    )
}

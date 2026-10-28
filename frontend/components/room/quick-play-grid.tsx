"use client"

import {Loader2, Music} from "lucide-react"
import type {QuickPlaySong} from "@/types/room"

interface QuickPlayGridProps {
    songs: QuickPlaySong[]
    isLoading: boolean
    addingSongId: string | null
    onSelect: (song: QuickPlaySong) => void
}

export function QuickPlayGrid({songs, isLoading, addingSongId, onSelect}: QuickPlayGridProps) {
    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-white/60 mb-4"/>
                <p className="text-white/60">載入推薦歌曲中...</p>
            </div>
        )
    }

    if (songs.length === 0) {
        return (
            <div className="text-center text-white/60 py-8">
                <Music className="h-12 w-12 mx-auto mb-4 opacity-50" strokeWidth={2}/>
                <p>目前沒有播放歌曲</p>
                <p className="text-sm mt-2">透過 LINE Bot 點歌開始播放</p>
            </div>
        )
    }

    return (
        <div className="space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between mb-2">
                <h2 className="text-white font-bold text-lg ml-1.5">快速播放</h2>
                <svg
                    className="w-5 h-5 text-white/60 mr-1"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
                </svg>
            </div>

            {/* Grid of songs */}
            <div className="grid grid-cols-3 gap-2">
                {songs.slice(0, 9).map((song) => (
                    <button
                        key={song.id}
                        onClick={() => onSelect(song)}
                        disabled={addingSongId !== null}
                        className="relative aspect-square rounded-lg overflow-hidden group focus:outline-none focus:ring-2 focus:ring-white/50 disabled:opacity-50"
                    >
                        <img
                            src={song.thumbnail || "/placeholder.jpg"}
                            alt={song.title}
                            className="w-full h-full object-cover transition-transform duration-200 group-hover:scale-105 group-active:scale-95"
                        />
                        {/* Gradient overlay */}
                        <div
                            className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent"/>

                        {/* Song title at bottom */}
                        <div className="absolute bottom-0 left-0 right-0 p-2">
                            <p className="text-white text-xs font-medium text-left line-clamp-2 leading-tight">
                                {song.title}
                            </p>
                        </div>

                        {/* Loading indicator when this song is being added */}
                        {addingSongId === song.id && (
                            <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
                                <Loader2 className="h-6 w-6 animate-spin text-white"/>
                            </div>
                        )}

                        {/* Hover/active overlay */}
                        <div
                            className="absolute inset-0 bg-white/10 opacity-0 group-hover:opacity-100 group-active:opacity-100 transition-opacity"/>
                    </button>
                ))}
            </div>
        </div>
    )
}

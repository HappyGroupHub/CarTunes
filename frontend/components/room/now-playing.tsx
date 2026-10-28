"use client"

import {Button} from "@/components/ui/button"
import {Progress} from "@/components/ui/progress"
import {AlertCircle, Download, Loader2, Pause, Play, Repeat1, SkipForward, User} from "lucide-react"
import {formatTime} from "@/lib/utils"
import type {Song} from "@/types/room"

export interface AudioStatus {
    songDownloading: boolean
    audioLoading: boolean
    audioError: string | null
    isNewUserLoadingAudio: boolean
    isCheckingStatus: boolean
}

interface NowPlayingProps {
    song: Song
    currentTime: number
    isPlaying: boolean
    canSkip: boolean
    isRepeat: boolean
    audioStatus: AudioStatus
    onTogglePlayback: () => void
    onSkip: () => void
    onToggleRepeat: () => void
}

export function NowPlaying({
                               song,
                               currentTime,
                               isPlaying,
                               canSkip,
                               isRepeat,
                               audioStatus,
                               onTogglePlayback,
                               onSkip,
                               onToggleRepeat,
                           }: NowPlayingProps) {
    const {songDownloading, audioLoading, audioError, isNewUserLoadingAudio, isCheckingStatus} = audioStatus
    const progress = (currentTime / song.duration) * 100
    const showStatus = songDownloading || audioLoading || audioError || isNewUserLoadingAudio || isCheckingStatus

    return (
        <>
            <div className="flex items-center mb-3">
                {/* Song Thumbnail */}
                {song.thumbnail && (
                    <img
                        src={song.thumbnail || "/placeholder.jpg"}
                        alt={song.title}
                        className="w-28 h-28 rounded-lg object-cover mr-4"
                    />
                )}
                {/* Song Info (Title, Channel, Requester) */}
                <div className="flex-1 min-w-0 text-left">
                    <h2 className="text-white font-bold text-base line-clamp-2 mb-1">{song.title}</h2>
                    {song.channel && (
                        <p className="text-white/70 text-sm truncate mb-1">{song.channel}</p>
                    )}
                    <div className="flex items-center space-x-1 text-white/60 text-xs">
                        <User className="h-3 w-3" strokeWidth={2}/>
                        <span>{song.requester_name}</span>
                    </div>
                </div>
            </div>

            {/* Audio Status Indicators */}
            {showStatus && (
                <div className="flex items-center justify-center space-x-2 mt-2 mb-2 text-sm">
                    {songDownloading && (
                        <span className="text-blue-400 flex items-center">
                            <Download className="h-4 w-4 animate-bounce mr-1" strokeWidth={2}/>
                            音訊載入中...
                        </span>
                    )}
                    {isNewUserLoadingAudio && !songDownloading && (
                        <span className="text-blue-400 flex items-center">
                            <Loader2 className="h-4 w-4 animate-spin mr-1" strokeWidth={2}/>
                            音訊載入中...
                        </span>
                    )}
                    {isCheckingStatus && !songDownloading && !isNewUserLoadingAudio && (
                        <span className="text-yellow-400 flex items-center">
                            <Loader2 className="h-4 w-4 animate-spin mr-1" strokeWidth={2}/>
                            檢查音訊狀態...
                        </span>
                    )}
                    {audioLoading && !songDownloading && !isNewUserLoadingAudio && !isCheckingStatus && (
                        <span className="text-white/60 flex items-center">
                            <Loader2 className="h-4 w-4 animate-spin mr-1" strokeWidth={2}/>
                            音訊載入中...
                        </span>
                    )}
                    {audioError && !songDownloading && !isNewUserLoadingAudio && (
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
                        <span>{formatTime(song.duration)}</span>
                    </div>
                </div>
                {/* Controls */}
                <div className="flex flex-col justify-start">
                    <div className="flex items-center space-x-2 -mt-4">
                        <Button
                            onClick={onToggleRepeat}
                            size="icon"
                            variant="ghost"
                            className={`${isRepeat ? "text-green-400 active:text-green-400 md:hover:text-green-400 bg-white/20" : "text-white/60 active:text-white md:hover:text-white"} active:bg-white/30 md:hover:bg-white/30 rounded-full w-8 h-8`}
                            aria-label={isRepeat ? "Disable repeat" : "Enable repeat"}
                            aria-pressed={isRepeat}
                        >
                            <Repeat1 className="h-4 w-4" strokeWidth={2}/>
                        </Button>
                        <Button
                            onClick={onTogglePlayback}
                            disabled={audioLoading || songDownloading || isNewUserLoadingAudio || isCheckingStatus}
                            size="icon"
                            className="bg-white/20 active:bg-white/30 md:hover:bg-white/30 text-white rounded-full w-10 h-10 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isPlaying ? (
                                <Pause className="h-5 w-5" strokeWidth={2}/>
                            ) : (
                                <Play className="h-5 w-5" strokeWidth={2}/>
                            )}
                        </Button>
                        <Button
                            onClick={onSkip}
                            disabled={!canSkip}
                            size="icon"
                            className="bg-white/20 active:bg-white/30 md:hover:bg-white/30 text-white rounded-full w-10 h-10"
                        >
                            <SkipForward className="h-5 w-5" strokeWidth={2}/>
                        </Button>
                    </div>
                </div>
            </div>
        </>
    )
}

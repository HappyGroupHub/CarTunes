"use client"

import React from "react"
import {Button} from "@/components/ui/button"
import {Badge} from "@/components/ui/badge"
import {Music, Share2, Users, Volume2, VolumeX, Wifi, WifiOff} from "lucide-react"
import type {StatusMessage} from "@/hooks/use-status-message"

interface RoomHeaderProps {
    roomId: string
    activeUsers: number
    isConnected: boolean
    isMuted: boolean
    statusMessage: StatusMessage | null
    statusMessageOpacity: number
    onCopyRoomId: () => void
    onShare: () => void
    onToggleMute: () => void
}

export function RoomHeader({
                               roomId,
                               activeUsers,
                               isConnected,
                               isMuted,
                               statusMessage,
                               statusMessageOpacity,
                               onCopyRoomId,
                               onShare,
                               onToggleMute,
                           }: RoomHeaderProps) {
    return (
        <div className="bg-black/20 backdrop-blur-sm p-4">
            <div className="flex items-center justify-between max-w-md mx-auto">
                <div className="flex items-center space-x-2">
                    {/* Make this whole div clickable for copying room ID */}
                    <div
                        onClick={onCopyRoomId}
                        className="flex items-center space-x-2 cursor-pointer active:bg-white/10 md:hover:bg-white/10 p-1 rounded-md transition-colors"
                    >
                        <Music className="h-6 w-6 text-white" strokeWidth={2}/>
                        <span className="text-white font-semibold">房間 {roomId}</span>
                    </div>

                    <Button
                        onClick={onShare}
                        size="icon"
                        variant="ghost"
                        className="text-white active:bg-white/20 md:hover:bg-white/20 w-8 h-8 flex-shrink-0 p-0"
                    >
                        <Share2 className="h-4 w-4"/>
                    </Button>

                    {/* Mute Button - hidden while its status message is showing */}
                    {!statusMessage?.hidesMuteButton && (
                        <Button
                            onClick={onToggleMute}
                            size="icon"
                            variant="ghost"
                            className={`${isMuted ? "text-red-500 active:bg-red-500/20 md:hover:bg-red-500/20" : "text-white active:bg-white/20 md:hover:bg-white/20"} w-8 h-8`}
                            aria-label={isMuted ? "Unmute audio" : "Mute audio"}
                        >
                            {isMuted ? <VolumeX className="h-4 w-4"/> : <Volume2 className="h-4 w-4"/>}
                        </Button>
                    )}

                    {statusMessage && (
                        <span
                            className={`${statusMessage.color} flex items-center text-sm ml-2 transition-opacity duration-500 ease-out`}
                            style={{opacity: statusMessageOpacity}}
                        >
                            {statusMessage.icon && React.createElement(statusMessage.icon, {className: "h-4 w-4 mr-1"})}
                            {statusMessage.text}
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
                        {activeUsers}
                    </Badge>
                </div>
            </div>
        </div>
    )
}

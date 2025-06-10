"use client"

import {Button} from "@/components/ui/button"
import {Card, CardContent, CardHeader, CardTitle} from "@/components/ui/card"
import {Music, MessageCircle, ExternalLink} from "lucide-react"
import {LINE_CONFIG} from "@/lib/config"

export default function HomePage() {
    const handleJoinLine = () => {
        window.open(LINE_CONFIG.BOT_URL, "_blank")
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-purple-600 via-blue-600 to-cyan-600 p-4">
            <div className="max-w-md mx-auto pt-20">
                <div className="text-center mb-8">
                    <div className="flex justify-center mb-4">
                        <div className="bg-white/20 backdrop-blur-sm rounded-full p-4">
                            <Music className="h-12 w-12 text-white"/>
                        </div>
                    </div>
                    <h1 className="text-3xl font-bold text-white mb-2">CarTunes</h1>
                    <p className="text-white/80">即時協作音樂播放器</p>
                </div>

                <Card className="bg-white/10 backdrop-blur-sm border-white/20">
                    <CardHeader>
                        <CardTitle className="text-white text-center">開始使用</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <div className="text-center">
                            <div className="bg-white/10 rounded-lg p-6 mb-6">
                                <MessageCircle className="h-16 w-16 text-white/80 mx-auto mb-4"/>
                                <h3 className="text-white font-semibold mb-2">透過 LINE Bot 點歌</h3>
                                <p className="text-white/70 text-sm">加入我們的 LINE
                                    官方帳號，即可開始點歌並獲得房間連結</p>
                            </div>

                            <Button
                                onClick={handleJoinLine}
                                className="w-full bg-green-600 hover:bg-green-700 text-white border-0 h-12 text-lg font-semibold"
                            >
                                <MessageCircle className="h-5 w-5 mr-2"/>
                                加入 LINE 好友開始使用
                                <ExternalLink className="h-4 w-4 ml-2"/>
                            </Button>
                        </div>
                    </CardContent>
                </Card>

                <div className="mt-8 text-center space-y-2">
                    <p className="text-white/60 text-sm">🎵 即時同步播放</p>
                    <p className="text-white/60 text-sm">🎧 多人協作點歌</p>
                    <p className="text-white/60 text-sm">📱 手機優化體驗</p>
                </div>
            </div>
        </div>
    )
}

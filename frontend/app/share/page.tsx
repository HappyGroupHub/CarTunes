"use client"

import {useEffect, Suspense} from "react"
import {useSearchParams} from "next/navigation"
import liff from "@line/liff"
import {LINE_CONFIG} from "@/lib/config"
import {Loader2, Music} from "lucide-react"

function ShareContent() {
    const searchParams = useSearchParams()
    const roomId = searchParams.get("roomId")

    useEffect(() => {
        const initLiff = async () => {
            try {
                await liff.init({liffId: LINE_CONFIG.LIFF_ID})
                if (!liff.isLoggedIn()) {
                    liff.login()
                    return
                }

                if (liff.isApiAvailable("shareTargetPicker") && roomId) {
                    const result = await liff.shareTargetPicker([
                        {
                            type: "flex",
                            altText: "有人邀請你一起在 CarTunes 聽歌！",
                            contents: {
                                type: "bubble",
                                hero: {
                                    type: "image",
                                    url: "https://i.imgur.com/zSJgfAT.jpeg", // 建議換成您的 App Logo 或封面
                                    size: "full", aspectRatio: "20:13", aspectMode: "cover"
                                },
                                body: {
                                    type: "box", layout: "vertical",
                                    contents: [
                                        {type: "text", text: "🎵 CarTunes 聽歌邀請", weight: "bold", size: "xl"},
                                        {
                                            type: "text",
                                            text: "點擊下方按鈕立即加入房間，一起同步聽歌、點歌！",
                                            wrap: true,
                                            margin: "md",
                                            size: "sm",
                                            color: "#666666"
                                        }
                                    ]
                                },
                                footer: {
                                    type: "box", layout: "vertical",
                                    contents: [
                                        {
                                            type: "button", style: "primary", color: "#9333ea",
                                            action: {
                                                type: "uri", label: "立即進入房間",
                                                // 使用 LINE URL Scheme 達成自動預填訊息
                                                uri: `https://line.me/R/oaMessage/${LINE_CONFIG.BOT_ID}/?房間代碼：${roomId}`
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    ])
                    // Close window after shared
                    liff.closeWindow()
                }
            } catch (err) {
                console.error("LIFF Init Error:", err)
                liff.closeWindow();
            }
        }

        initLiff()
    }, [roomId])

    return (
        <div
            className="min-h-screen bg-gradient-to-br from-purple-600 to-blue-600 flex items-center justify-center text-white">
            <div className="text-center">
                <Loader2 className="h-10 w-10 animate-spin mx-auto mb-4"/>
                <p className="font-medium">正在開啟 LINE 好友清單...</p>
            </div>
        </div>
    )
}

export default function SharePage() {
    return (
        <Suspense>
            <ShareContent/>
        </Suspense>
    )
}
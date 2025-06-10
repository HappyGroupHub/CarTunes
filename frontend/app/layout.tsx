import type React from "react"
import type {Metadata} from "next"
import {Inter} from "next/font/google"
import "./globals.css"

const inter = Inter({subsets: ["latin"]})

export const metadata: Metadata = {
    title: "CarTunes - 即時協作音樂播放器",
    description: "Real-time collaborative music player for road trips",
    generator: 'v0.dev'
}

export default function RootLayout({children,}: {
    children: React.ReactNode
}) {
    return (
        <html lang="zh-TW">
        <body className={inter.className}>{children}</body>
        </html>
    )
}

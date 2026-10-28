"use client"

import {Button} from "@/components/ui/button"
import {Modal} from "@/components/ui/modal"
import {AlertCircle} from "lucide-react"

interface MessageModalProps {
    isOpen: boolean
    message: string
    buttonText: string
    onAction: () => void
}

// Generic notice modal, message may contain HTML
export function MessageModal({isOpen, message, buttonText, onAction}: MessageModalProps) {
    return (
        <Modal
            isOpen={isOpen}
            onClose={onAction}
            title="提示"
        >
            <div className="text-center py-2">
                <div
                    className="text-gray-700 mb-4"
                    dangerouslySetInnerHTML={{__html: message}}
                />
                <Button onClick={onAction} className="w-full">
                    {buttonText}
                </Button>
            </div>
        </Modal>
    )
}

interface RefreshModalProps {
    isOpen: boolean
    onClose: () => void
}

// Shown when audio playback keeps failing after all retries
export function RefreshModal({isOpen, onClose}: RefreshModalProps) {
    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title="提示"
        >
            <div className="bg-white rounded-lg p-6 max-w-md mx-auto">
                <div className="flex items-center mb-4">
                    <AlertCircle className="h-6 w-6 text-red-500 mr-2"/>
                    <h2 className="text-lg font-semibold">音訊播放問題</h2>
                </div>
                <p className="text-gray-600 mb-4">
                    音訊播放持續失敗，可能是網路問題或瀏覽器限制。
                    請重新整理頁面再試一次。
                </p>
                <div className="flex space-x-3">
                    <Button
                        onClick={() => window.location.reload()}
                        className="flex-1"
                    >
                        重新整理頁面
                    </Button>
                    <Button
                        variant="outline"
                        onClick={onClose}
                        className="flex-1"
                    >
                        繼續嘗試
                    </Button>
                </div>
            </div>
        </Modal>
    )
}

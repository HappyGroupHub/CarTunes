"use client"

import type React from "react"

import {useEffect} from "react"
import {X} from "lucide-react"
import {Button} from "./button"

interface ModalProps {
    isOpen: boolean
    onClose: () => void
    title: string
    children: React.ReactNode
}

export function Modal({isOpen, onClose, title, children}: ModalProps) {
    useEffect(() => {
        if (isOpen) {
            document.body.style.overflow = "hidden"
        } else {
            document.body.style.overflow = "unset"
        }

        return () => {
            document.body.style.overflow = "unset"
        }
    }, [isOpen])

    if (!isOpen) return null

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            {/* Backdrop */}
            <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose}/>

            {/* Modal */}
            <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto">
                {/* Header */}
                <div className="flex items-center justify-between p-2 border-b">
                    <h2 className="text-md font-semibold text-gray-900 ml-2">{title}</h2>
                    <Button onClick={onClose} variant="ghost" size="sm" className="h-8 w-8 p-0">
                        <X className="h-4 w-4"/>
                    </Button>
                </div>

                {/* Content */}
                <div className="p-4">{children}</div>
            </div>
        </div>
    )
}

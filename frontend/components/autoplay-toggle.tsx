"use client"

import {Play, Pause} from "lucide-react"

interface AutoplayToggleProps {
    isEnabled: boolean
    onToggle: () => void
}

export function AutoplayToggle({isEnabled, onToggle}: AutoplayToggleProps) {
    return (
        <button
            onClick={onToggle}
            className={`relative inline-flex h-4 w-8 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-white/20 ${
                isEnabled ? "bg-gray-400" : "bg-gray-400"
            }`}
            aria-label="Toggle autoplay"
        >
      <span
          className={`inline-block h-3 w-3 transform rounded-full transition-transform flex items-center justify-center ${
              isEnabled ? "translate-x-[1.125rem] bg-white" : "translate-x-0.5 bg-gray-500"
          }`}
      >
        {isEnabled ? (
            <Play className="h-[0.7rem] w-[0.7rem] text-gray-700" strokeWidth={2} style={
                { transform: "translate(1px, 0.5px)" }}/>
        ) : (
            <Pause className="h-3 w-3 text-white" strokeWidth={2}/>
        )}
      </span>
        </button>
    )
}

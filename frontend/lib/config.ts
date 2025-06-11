// API Configuration
export const API_CONFIG = {
  BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  WS_BASE_URL: process.env.NEXT_PUBLIC_WS_BASE_URL,
} as const

// LINE Configuration
export const LINE_CONFIG = {
  LIFF_ID: process.env.NEXT_PUBLIC_LINE_LIFF_ID || "",
  BOT_URL: process.env.NEXT_PUBLIC_LINE_BOT_URL || "https://google.com",
} as const

// API Endpoints
export const API_ENDPOINTS = {
  // Base URL for custom endpoints
  BASE_URL: API_CONFIG.BASE_URL,

  // Room endpoints
  ROOM: (roomId: string) => `${API_CONFIG.BASE_URL}/api/room/${roomId}`,

  // Playback endpoints
  PLAYBACK: (roomId: string) => `${API_CONFIG.BASE_URL}/api/room/${roomId}/playback`,
  SKIP_NEXT: (roomId: string) => `${API_CONFIG.BASE_URL}/api/room/${roomId}/queue/next`,

  // Queue endpoints
  REMOVE_SONG: (roomId: string, songId: string) => `${API_CONFIG.BASE_URL}/api/room/${roomId}/queue/${songId}`,
  REORDER_QUEUE: (roomId: string) => `${API_CONFIG.BASE_URL}/api/room/${roomId}/queue/reorder`,

  // Audio endpoints
  AUDIO_INFO: (videoId: string) => `${API_CONFIG.BASE_URL}/api/audio/${videoId}`,
  AUDIO_STREAM: (videoId: string) => `${API_CONFIG.BASE_URL}/api/stream/${videoId}`,

  // WebSocket endpoint
  WEBSOCKET: (roomId: string) => `${API_CONFIG.WS_BASE_URL}/ws/${roomId}`,
} as const
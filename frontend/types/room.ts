export interface Song {
    id: string
    video_id: string
    title: string
    channel?: string
    duration: number
    thumbnail?: string
    requester_id: string
    requester_name: string
    added_at: string
}

export interface PlaybackState {
    is_playing: boolean
    current_time: number
    last_updated: string
}

export interface RoomMember {
    user_id: string
    user_name: string
    joined_at: string
}

export interface Room {
    room_id: string
    members: RoomMember[]
    queue: Song[]
    current_song: Song | null
    playback_state: PlaybackState
    active_users: number
    autoplay: boolean
}

export interface QuickPlaySong {
    id: string
    title: string
    channel: string
    thumbnail: string
    type: string
    duration: number
    lang_tag?: string
}

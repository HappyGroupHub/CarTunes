import {API_ENDPOINTS} from "./config"

interface LoadAudioCallbacks {
    setAudioLoading: (loading: boolean) => void
    setAudioError: (error: string | null) => void
    setSongDownloading: (downloading: boolean) => void
    onLoadedMetadata: (audioElement: HTMLAudioElement, initialTime: number) => void
    onCanPlay: (audioElement: HTMLAudioElement, isPlaying: boolean, userHasInteracted: boolean) => void
}

export function loadAudio(
    audioElement: HTMLAudioElement | null,
    videoId: string,
    callbacks: LoadAudioCallbacks,
    initialTime = 0,
    isPlaying = false,
    userHasInteracted = false,
): () => void {
    if (!audioElement) return () => {
    }

    const {setAudioLoading, setAudioError, setSongDownloading, onLoadedMetadata, onCanPlay} = callbacks

    let loadingTimeout: NodeJS.Timeout | null = null

    const handleLoadStart = () => {
        console.log("📡 Audio loading started")
        setAudioLoading(true)
        setAudioError(null)
    }

    const handleCanPlayEvent = () => {
        console.log("✅ Audio can play - loading complete!")
        setAudioLoading(false)
        setAudioError(null)
        if (loadingTimeout) {
            clearTimeout(loadingTimeout)
            loadingTimeout = null
        }
        onCanPlay(audioElement, isPlaying, userHasInteracted)
    }

    const handleError = (event: Event) => {
        console.error("❌ Audio error event:", event)
        const error = audioElement.error
        console.error("🚫 Audio element error details:", {
            code: error?.code,
            message: error?.message,
            MEDIA_ERR_ABORTED: error?.code === 1,
            MEDIA_ERR_NETWORK: error?.code === 2,
            MEDIA_ERR_DECODE: error?.code === 3,
            MEDIA_ERR_SRC_NOT_SUPPORTED: error?.code === 4,
        })

        let errorMessage = "無法載入音訊"
        if (error) {
            switch (error.code) {
                case 1:
                    errorMessage = "音訊載入被中止"
                    break
                case 2:
                    errorMessage = "網路錯誤"
                    break
                case 3:
                    errorMessage = "音訊解碼失敗"
                    break
                case 4:
                    errorMessage = "音訊格式不支援"
                    break
            }
        }
        console.error(`🔍 Setting error message: ${errorMessage}`)
        setAudioError(errorMessage)
        setAudioLoading(false)
        if (loadingTimeout) {
            clearTimeout(loadingTimeout)
            loadingTimeout = null
        }
    }

    const handleLoadedData = () => {
        console.log("📊 Audio data loaded successfully")
        setAudioLoading(false)
        if (loadingTimeout) {
            clearTimeout(loadingTimeout)
            loadingTimeout = null
        }
    }

    const handleLoadedMetadataEvent = () => {
        console.log("📋 Audio metadata loaded")
        onLoadedMetadata(audioElement, initialTime)
    }

    const handleProgress = () => {
        if (audioElement) {
            const buffered = audioElement.buffered
            if (buffered.length > 0) {
                const loaded = (buffered.end(buffered.length - 1) / audioElement.duration) * 100
                console.log(`📈 Audio loading progress: ${loaded.toFixed(1)}%`)
            }
        }
    }

    const handleSuspend = () => {
        console.log("⏸️ Audio loading suspended")
    }

    const handleStalled = () => {
        console.log("🐌 Audio loading stalled")
    }

    // Remove any existing event listeners first to prevent duplicates
    audioElement.removeEventListener("loadstart", handleLoadStart)
    audioElement.removeEventListener("canplay", handleCanPlayEvent)
    audioElement.removeEventListener("error", handleError)
    audioElement.removeEventListener("loadeddata", handleLoadedData)
    audioElement.removeEventListener("loadedmetadata", handleLoadedMetadataEvent)
    audioElement.removeEventListener("progress", handleProgress)
    audioElement.removeEventListener("suspend", handleSuspend)
    audioElement.removeEventListener("stalled", handleStalled)

    // Add comprehensive event listeners
    audioElement.addEventListener("loadstart", handleLoadStart)
    audioElement.addEventListener("canplay", handleCanPlayEvent)
    audioElement.addEventListener("error", handleError)
    audioElement.addEventListener("loadeddata", handleLoadedData)
    audioElement.addEventListener("loadedmetadata", handleLoadedMetadataEvent)
    audioElement.addEventListener("progress", handleProgress)
    audioElement.addEventListener("suspend", handleSuspend)
    audioElement.addEventListener("stalled", handleStalled)

    // Set a timeout for loading
    loadingTimeout = setTimeout(() => {
        console.error("⏰ Audio loading timeout after 30 seconds")
        setAudioLoading(false)
        setAudioError("載入超時")
    }, 30000)

    const audioUrl = API_ENDPOINTS.AUDIO_STREAM(videoId)
    console.log(`🔗 Audio URL: ${audioUrl}`)

    // Check if the URL is accessible (HEAD request)
    console.log("🔍 Testing audio URL accessibility (HEAD request)...")
    fetch(audioUrl, {
        method: "HEAD",
        mode: "cors",
    })
        .then((response) => {
            console.log(`🌐 URL test response (HEAD):`, {
                status: response.status,
                statusText: response.statusText,
                headers: Object.fromEntries(response.headers.entries()),
            })

            if (response.status === 202) {
                console.log("⏳ Audio is still downloading on server (HEAD response 202)...")
                setSongDownloading(true)
            } else if (response.status === 404) {
                console.log("❌ Audio not found on server (HEAD response 404)")
                setAudioError("歌曲不存在或無法下載")
                setAudioLoading(false)
                setSongDownloading(false)
                if (loadingTimeout) clearTimeout(loadingTimeout)
            } else if (response.ok) {
                console.log("✅ Audio is ready on server (HEAD response 200)")
                setSongDownloading(false)
            }
        })
        .catch((fetchError) => {
            console.error("🚨 URL accessibility test (HEAD) failed:", fetchError)
            setAudioError("網路連線錯誤")
            setAudioLoading(false)
            setSongDownloading(false)
            if (loadingTimeout) clearTimeout(loadingTimeout)
        })
        .finally(() => {
            audioElement.src = audioUrl
            console.log(`🎯 Audio src set to: ${audioElement.src}`)
            audioElement.load()
            console.log("🚀 Audio.load() called")
        })

    // Return a cleanup function
    return () => {
        audioElement.removeEventListener("loadstart", handleLoadStart)
        audioElement.removeEventListener("canplay", handleCanPlayEvent)
        audioElement.removeEventListener("error", handleError)
        audioElement.removeEventListener("loadeddata", handleLoadedData)
        audioElement.removeEventListener("loadedmetadata", handleLoadedMetadataEvent)
        audioElement.removeEventListener("progress", handleProgress)
        audioElement.removeEventListener("suspend", handleSuspend)
        audioElement.removeEventListener("stalled", handleStalled)
        if (loadingTimeout) {
            clearTimeout(loadingTimeout)
        }
        console.log("🧹 Audio event listeners cleaned up (from loadAudio return)")
    }
}

import { useEffect, useState } from 'react'
import { z } from 'zod'
import { parseServerMessage, type ServerMessage } from '../../shared/contracts'

type BackendNowPlayingEvent = Extract<ServerMessage, { type: 'media.now-playing' }>
type PlayerTrack = Omit<BackendNowPlayingEvent, 'type' | 'protocolVersion' | 'messageId' | 'timestamp' | 'provider'> & {
  provider: BackendNowPlayingEvent['provider'] | 'youtube'
}

const hostedMediaEventSchema = z.object({
  instanceId: z.string().uuid(),
  active: z.boolean(),
  media: z.object({
    provider: z.literal('youtube'),
    title: z.string(),
    artist: z.string(),
    album: z.string(),
    artworkUrl: z.url().nullable(),
    durationMs: z.number().int().nonnegative(),
    progressMs: z.number().int().nonnegative(),
    isPlaying: z.boolean()
  }).optional()
})

const formatTime = (milliseconds: number) => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export function NowPlaying() {
  const [track, setTrack] = useState<PlayerTrack | null>(null)
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    const bridge = window.darwinAssistantSession
    if (!bridge) return
    const subscription = bridge.subscribeEvents((value) => {
      try {
        const event = parseServerMessage(value)
        if (event.type === 'media.now-playing') {
          setTrack(event as PlayerTrack)
          setProgress(event.progressMs)
        }
      } catch {
        // The media card ignores unrelated or invalid assistant events.
      }
    })
    return () => bridge.unsubscribe(subscription)
  }, [])

  useEffect(() => {
    const bridge = window.darwinWebApps
    if (!bridge?.subscribeMedia) return
    const subscription = bridge.subscribeMedia((value) => {
      const parsed = hostedMediaEventSchema.safeParse(value)
      if (!parsed.success) return
      if (!parsed.data.active || !parsed.data.media) {
        setTrack((current) => current?.provider === 'youtube' ? null : current)
        return
      }
      setTrack(parsed.data.media)
      setProgress(parsed.data.media.progressMs)
    })
    return () => bridge.unsubscribeMedia(subscription)
  }, [])

  useEffect(() => {
    if (!track?.isPlaying) return
    const timer = window.setInterval(
      () => setProgress((value) => Math.min(track.durationMs, value + 1_000)),
      1_000
    )
    return () => window.clearInterval(timer)
  }, [track])

  if (!track) return null

  const control = (action: 'pause' | 'resume' | 'next' | 'previous') => {
    if (action === 'pause' || action === 'resume') {
      setTrack((current) =>
        current ? { ...current, isPlaying: action === 'resume' } : current
      )
    }
    if (track.provider === 'youtube') void window.darwinWebApps?.controlMedia(action)
    else void window.darwinAssistantSession?.controlMedia(action)
  }

  return (
    <aside className="now-playing" aria-label="Now playing">
      {track.artworkUrl && (
        <div
          className="now-playing__ambient"
          style={{ backgroundImage: `url(${track.artworkUrl})` }}
          aria-hidden="true"
        />
      )}
      <small className="now-playing__provider">
        {track.provider === 'apple_music' ? 'Apple Music' : track.provider}
      </small>
      <div className="now-playing__art" aria-hidden="true">
        {track.artworkUrl ? <img src={track.artworkUrl} alt="" /> : <span>♪</span>}
      </div>
      <div className="now-playing__details">
        <div className="now-playing__metadata">
          <strong>{track.title}</strong>
          <span>{track.artist}</span>
        </div>
        <div className="now-playing__progress">
          <i style={{ width: `${track.durationMs ? (progress / track.durationMs) * 100 : 0}%` }} />
        </div>
        <div className="now-playing__time">
          <small>{formatTime(progress)}</small>
          <small>-{formatTime(Math.max(0, track.durationMs - progress))}</small>
        </div>
        <div className="now-playing__controls">
          <button type="button" aria-label="Previous track" onClick={() => control('previous')}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5v14M18 6l-9 6 9 6V6Z" /></svg>
          </button>
          <button
            type="button"
            className="now-playing__primary"
            aria-label={track.isPlaying ? 'Pause music' : 'Resume music'}
            onClick={() => control(track.isPlaying ? 'pause' : 'resume')}
          >
            {track.isPlaying ? (
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6v12M16 6v12" /></svg>
            ) : (
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 9 6-9 6V6Z" /></svg>
            )}
          </button>
          <button type="button" aria-label="Next track" onClick={() => control('next')}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 5v14M6 6l9 6-9 6V6Z" /></svg>
          </button>
        </div>
      </div>
    </aside>
  )
}

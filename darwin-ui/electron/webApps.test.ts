import { describe, expect, it } from 'vitest'
import {
  mediaDuckingScript,
  optimizedYouTubeUserAgent,
  youtubeMediaSnapshotScript
} from './webApps.js'

describe('embedded media ducking', () => {
  it('preserves the original volume and applies the configured ratio', () => {
    const script = mediaDuckingScript(true, 0.25)

    expect(script).toContain('controller.originalVolumes.set(media, media.volume)')
    expect(script).toContain('controller.originalVolumes.get(media) * controller.ratio')
    expect(script).toContain('controller.ratio = 0.25')
    expect(script).toContain("media.addEventListener('volumechange', holdVolume)")
    expect(script).toContain("document.querySelectorAll('audio,video')")
  })

  it('restores the saved volume and removes the temporary value', () => {
    const script = mediaDuckingScript(false, 0.25)

    expect(script).toContain("media.removeEventListener('volumechange', listener)")
    expect(script).toContain('media.volume = Math.max(0, Math.min(1, originalVolume))')
    expect(script).toContain('controller.originalVolumes.clear()')
  })
})

describe('YouTube media snapshot', () => {
  it('reads only serializable playback metadata from the hosted page', () => {
    expect(youtubeMediaSnapshotScript).toContain("document.querySelector('video')")
    expect(youtubeMediaSnapshotScript).toContain('getVideoData')
    expect(youtubeMediaSnapshotScript).toContain('durationMs')
    expect(youtubeMediaSnapshotScript).toContain('progressMs')
    expect(youtubeMediaSnapshotScript).toContain('isPlaying')
  })

  it('uses a Chrome-compatible user agent without exposing Electron', () => {
    expect(
      optimizedYouTubeUserAgent(
        'Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36 Electron/44.3.0'
      )
    ).toBe('Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36')
  })
})

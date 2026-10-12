import { BrowserWindow, WebContentsView, ipcMain, session, shell } from 'electron'
import { z } from 'zod'
import {
  isAllowedWebUrl,
  validateWebAppRequest,
  webAppIdSchema,
  webAppNavigationSchema,
  webAppUpdateSchema,
  type WebAppCreateRequest
} from './webSecurity.js'
import {
  APP_OVERLAY_CLEAR_RADIUS_PX,
  APP_OVERLAY_THICKNESS_PX
} from '../shared/visualConfig.js'

type WebAppStatus =
  | 'loading'
  | 'ready'
  | 'offline'
  | 'certificate-error'
  | 'crashed'
  | 'error'
  | 'fullscreen-enter'
  | 'fullscreen-leave'
  | 'chrome-reveal'
  | 'cinema-resize'
interface HostedView {
  view: WebContentsView
  request: WebAppCreateRequest
  bounds: Electron.Rectangle
  mediaTimer?: ReturnType<typeof setInterval>
  lastMediaSignature?: string
}

const hostedMediaSchema = z.object({
  title: z.string().trim().min(1).max(500),
  artist: z.string().max(500),
  album: z.string().max(500),
  artworkUrl: z.url().nullable(),
  durationMs: z.number().int().nonnegative().max(86_400_000),
  progressMs: z.number().int().nonnegative().max(86_400_000),
  isPlaying: z.boolean()
})

const mediaControlSchema = z.enum(['pause', 'resume', 'next', 'previous'])

const YOUTUBE_ORIGIN = 'https://www.youtube.com'
const YOUTUBE_PARTITION = 'persist:darwin.youtube'

export const optimizedYouTubeUserAgent = (userAgent: string) =>
  userAgent.replace(/\sElectron\/[\d.]+/i, '')

export const youtubeMediaSnapshotScript = `(() => {
  const video = document.querySelector('video');
  if (!(video instanceof HTMLVideoElement) || !video.currentSrc || !Number.isFinite(video.duration) || video.duration <= 0) return null;
  const player = document.querySelector('#movie_player');
  const data = typeof player?.getVideoData === 'function' ? player.getVideoData() : null;
  const title = String(data?.title || document.querySelector('h1.ytd-watch-metadata yt-formatted-string')?.textContent || document.title.replace(/\\s+-\\s+YouTube$/, '')).trim();
  if (!title) return null;
  const artist = String(data?.author || document.querySelector('#owner #channel-name a')?.textContent || '').trim();
  const videoId = String(data?.video_id || new URL(location.href).searchParams.get('v') || '').trim();
  const metaArtwork = document.querySelector('meta[property="og:image"]')?.getAttribute('content');
  const artworkUrl = videoId ? 'https://i.ytimg.com/vi/' + encodeURIComponent(videoId) + '/hqdefault.jpg' : (metaArtwork ? new URL(metaArtwork, location.href).href : null);
  return {
    title,
    artist,
    album: 'YouTube',
    artworkUrl,
    durationMs: Math.max(0, Math.round(video.duration * 1000)),
    progressMs: Math.max(0, Math.round(video.currentTime * 1000)),
    isPlaying: !video.paused && !video.ended
  };
})()`

const youtubeMediaControlScript = (action: z.infer<typeof mediaControlSchema>) => `(() => {
  const video = document.querySelector('video');
  if (!(video instanceof HTMLVideoElement)) return false;
  if (${JSON.stringify(action)} === 'pause') video.pause();
  if (${JSON.stringify(action)} === 'resume') void video.play();
  if (${JSON.stringify(action)} === 'next') document.querySelector('.ytp-next-button')?.click();
  if (${JSON.stringify(action)} === 'previous') {
    const previous = document.querySelector('.ytp-prev-button');
    if (previous instanceof HTMLElement) previous.click();
    else video.currentTime = 0;
  }
  return true;
})()`

const configuredMediaDuckRatio = () => {
  const value = Number(process.env.DARWIN_UI_MEDIA_DUCK_RATIO ?? '0.25')
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0.25
}

export const mediaDuckingScript = (ducked: boolean, ratio: number) => `(() => {
  const controllerKey = '__darwinMediaDucking';
  const root = window;
  let controller = root[controllerKey];
  if (!controller) {
    controller = root[controllerKey] = {
      active: false,
      ratio: 1,
      originalVolumes: new Map(),
      listeners: new Map(),
      observer: null
    };
  }
  const apply = media => {
    if (!(media instanceof HTMLMediaElement) || !controller.active) return;
    if (!controller.originalVolumes.has(media)) controller.originalVolumes.set(media, media.volume);
    const target = Math.max(0, Math.min(1, controller.originalVolumes.get(media) * controller.ratio));
    if (Math.abs(media.volume - target) > 0.001) media.volume = target;
    if (!controller.listeners.has(media)) {
      const holdVolume = () => queueMicrotask(() => apply(media));
      controller.listeners.set(media, holdVolume);
      media.addEventListener('volumechange', holdVolume);
    }
  };
  const scan = () => document.querySelectorAll('audio,video').forEach(apply);
  if (${JSON.stringify(ducked)}) {
    controller.active = true;
    controller.ratio = ${JSON.stringify(ratio)};
    scan();
    if (!controller.observer) {
      controller.observer = new MutationObserver(scan);
      controller.observer.observe(document.documentElement, { childList: true, subtree: true });
    }
  } else {
    controller.active = false;
    controller.observer?.disconnect();
    controller.observer = null;
    for (const [media, listener] of controller.listeners) {
      media.removeEventListener('volumechange', listener);
    }
    controller.listeners.clear();
    for (const [media, originalVolume] of controller.originalVolumes) {
      if (media.isConnected) media.volume = Math.max(0, Math.min(1, originalVolume));
    }
    controller.originalVolumes.clear();
  }
})()`

export class WebAppManager {
  readonly #window: BrowserWindow
  readonly #views = new Map<string, HostedView>()
  #voicePlaybackActive = false

  constructor(window: BrowserWindow) {
    this.#window = window
    const youtubeSession = session.fromPartition(YOUTUBE_PARTITION)
    youtubeSession.setUserAgent(optimizedYouTubeUserAgent(youtubeSession.getUserAgent()))
    youtubeSession.preconnect({ url: YOUTUBE_ORIGIN, numSockets: 6 })
    void youtubeSession
      .fetch(`${YOUTUBE_ORIGIN}/`, { method: 'GET' })
      .then((response) => response.arrayBuffer())
      .catch(() => undefined)
  }

  #emit(instanceId: string, status: WebAppStatus, detail?: string) {
    this.#window.webContents.send('web-app:event', { instanceId, status, detail })
  }

  #emitMedia(instanceId: string, media: z.infer<typeof hostedMediaSchema> | null) {
    if (this.#window.isDestroyed() || this.#window.webContents.isDestroyed()) return
    this.#window.webContents.send('web-app:media', {
      instanceId,
      active: media !== null,
      ...(media ? { media: { provider: 'youtube' as const, ...media } } : {})
    })
  }

  #startMediaTracking(hosted: HostedView) {
    if (hosted.request.appId !== 'darwin.youtube' || hosted.mediaTimer) return
    const sample = async () => {
      const contents = hosted.view.webContents
      if (contents.isDestroyed() || contents.isLoadingMainFrame()) return
      try {
        const parsed = hostedMediaSchema.safeParse(
          await contents.executeJavaScript(youtubeMediaSnapshotScript)
        )
        const media = parsed.success ? parsed.data : null
        const signature = media ? JSON.stringify(media) : 'inactive'
        if (signature === hosted.lastMediaSignature) return
        hosted.lastMediaSignature = signature
        this.#emitMedia(hosted.request.instanceId, media)
      } catch {
        // Navigation can invalidate JavaScript execution between polling ticks.
      }
    }
    void sample()
    hosted.mediaTimer = setInterval(() => void sample(), 1_000)
  }

  async create(value: unknown) {
    const request = validateWebAppRequest(value)
    if (this.#views.has(request.instanceId)) return { ok: true }
    const view = new WebContentsView({
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
        partition: `persist:${request.session}`,
        autoplayPolicy: 'no-user-gesture-required',
        backgroundThrottling: false,
        spellcheck: false
      }
    })
    view.setBounds(request.bounds)
    view.setBackgroundColor('#000000')
    view.setVisible(false)
    this.#window.contentView.addChildView(view)
    const hosted: HostedView = {
      view,
      request,
      bounds: request.bounds
    }
    this.#views.set(request.instanceId, hosted)
    const contents = view.webContents
    const allowPermission = (permission: string) =>
      permission === 'fullscreen' && request.permissions.includes('media.fullscreen')
    contents.session.setPermissionCheckHandler((_webContents, permission) =>
      allowPermission(permission)
    )
    contents.session.setPermissionRequestHandler((_webContents, permission, callback) =>
      callback(allowPermission(permission))
    )
    contents.session.setDevicePermissionHandler(() => false)
    contents.session.on('will-download', (event) => event.preventDefault())
    contents.setWindowOpenHandler(({ url }) => {
      if (isAllowedWebUrl(url, request.allowedOrigins)) void contents.loadURL(url)
      else if (url.startsWith('https://')) void shell.openExternal(url)
      return { action: 'deny' }
    })
    contents.on('will-navigate', (event, url) => {
      if (!isAllowedWebUrl(url, request.allowedOrigins)) event.preventDefault()
    })
    contents.on('did-start-loading', () => this.#emit(request.instanceId, 'loading'))
    const emitReady = () => {
      this.#emit(request.instanceId, 'ready')
      void contents.executeJavaScript(`(() => {
        if (!document.getElementById('darwin-window-chrome-trigger')) {
          const trigger = document.createElement('div');
          trigger.id = 'darwin-window-chrome-trigger';
          Object.assign(trigger.style, { position: 'fixed', top: '0', right: '0', left: '0', height: '10px', zIndex: '2147483647', background: 'transparent' });
          trigger.addEventListener('mouseenter', () => console.info('__DARWIN_REVEAL_CHROME__'));
          document.documentElement.appendChild(trigger);
        }
        if (${JSON.stringify(request.edgeEffect)} === 'flow' && !document.getElementById('darwin-edge-flow')) {
          const overlay = document.createElement('div');
          overlay.id = 'darwin-edge-flow';
          Object.assign(overlay.style, { position: 'fixed', inset: '0', zIndex: '2147483646', pointerEvents: 'none', background: 'linear-gradient(to bottom,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 96%,transparent) 4%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 55%,transparent) ${APP_OVERLAY_THICKNESS_PX * 0.5}px,transparent ${APP_OVERLAY_THICKNESS_PX}px),linear-gradient(to top,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 96%,transparent) 4%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 55%,transparent) ${APP_OVERLAY_THICKNESS_PX * 0.5}px,transparent ${APP_OVERLAY_THICKNESS_PX}px),linear-gradient(to right,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 50%,transparent) ${APP_OVERLAY_THICKNESS_PX * 0.5}px,transparent ${APP_OVERLAY_THICKNESS_PX}px),linear-gradient(to left,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 50%,transparent) ${APP_OVERLAY_THICKNESS_PX * 0.5}px,transparent ${APP_OVERLAY_THICKNESS_PX}px)', webkitMaskImage: 'radial-gradient(circle ${APP_OVERLAY_CLEAR_RADIUS_PX}px at var(--darwin-clear-x,-999px) var(--darwin-clear-y,-999px),rgb(0 0 0 / 20%) 0%,rgb(0 0 0 / 45%) 35%,rgb(0 0 0 / 75%) 72%,#000 100%)', maskImage: 'radial-gradient(circle ${APP_OVERLAY_CLEAR_RADIUS_PX}px at var(--darwin-clear-x,-999px) var(--darwin-clear-y,-999px),rgb(0 0 0 / 20%) 0%,rgb(0 0 0 / 45%) 35%,rgb(0 0 0 / 75%) 72%,#000 100%)' });
          (document.body || document.documentElement).appendChild(overlay);
          document.addEventListener('pointermove', event => {
            overlay.style.setProperty('--darwin-clear-x', event.clientX + 'px');
            overlay.style.setProperty('--darwin-clear-y', event.clientY + 'px');
          }, { passive: true });
          document.addEventListener('pointerleave', () => {
            overlay.style.setProperty('--darwin-clear-x', '-999px');
            overlay.style.setProperty('--darwin-clear-y', '-999px');
          });
        }
      })()`)
      if (this.#voicePlaybackActive) this.#setMediaDucked(hosted, true)
      this.#startMediaTracking(hosted)
    }
    contents.on('dom-ready', emitReady)
    contents.on('did-finish-load', emitReady)
    contents.on('did-fail-load', (_event, code, description, _url, isMainFrame) => {
      if (!isMainFrame || code === -3) return
      view.setVisible(false)
      this.#emit(request.instanceId, code === -106 ? 'offline' : 'error', description)
    })
    contents.on('render-process-gone', (_event, details) => {
      view.setVisible(false)
      this.#emit(request.instanceId, 'crashed', details.reason)
    })
    contents.on('certificate-error', () => {
      view.setVisible(false)
      this.#emit(request.instanceId, 'certificate-error')
    })
    contents.on('console-message', (_event, _level, message) => {
      if (message === '__DARWIN_REVEAL_CHROME__')
        this.#emit(request.instanceId, 'chrome-reveal')
      if (message.startsWith('__DARWIN_CINEMA_RESIZE__'))
        this.#emit(
          request.instanceId,
          'cinema-resize',
          message.slice('__DARWIN_CINEMA_RESIZE__'.length)
        )
    })
    contents.on('enter-html-full-screen', () => {
      this.#emit(request.instanceId, 'fullscreen-enter')
      void contents.executeJavaScript(`(() => {
        document.getElementById('darwin-cinema-overlay')?.remove();
        document.getElementById('darwin-cinema-corners')?.remove();
        let root = document.fullscreenElement || document.querySelector('#movie_player');
        if (root instanceof HTMLVideoElement) root = root.parentElement;
        if (!root) return false;
        const overlay = document.createElement('div');
        overlay.id = 'darwin-cinema-overlay';
        Object.assign(overlay.style, {
          position: 'fixed',
          inset: '-1px',
          overflow: 'hidden',
          zIndex: '2147483647',
          pointerEvents: 'none',
          background: 'linear-gradient(to bottom,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 96%,transparent) 4%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 55%,transparent) 13%,transparent 27%),linear-gradient(to top,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 96%,transparent) 4%,transparent 27%),linear-gradient(to right,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 55%,transparent) 13%,transparent 27%),linear-gradient(to left,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 55%,transparent) 13%,transparent 27%)',
          boxShadow: 'inset 0 0 9rem 3.5rem color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 82%,transparent)',
          webkitMaskImage: 'radial-gradient(circle 7rem at var(--darwin-overlay-x,-999px) var(--darwin-overlay-y,-999px),transparent 0%,transparent 42%,#000 100%)',
          maskImage: 'radial-gradient(circle 7rem at var(--darwin-overlay-x,-999px) var(--darwin-overlay-y,-999px),transparent 0%,transparent 42%,#000 100%)'
        });
        root.appendChild(overlay);
        overlay.style.display = 'none';
        const edgeFlow = document.getElementById('darwin-edge-flow');
        if (edgeFlow) root.appendChild(edgeFlow);
        root.addEventListener('mousemove', event => {
          overlay.style.setProperty('--darwin-overlay-x', event.clientX + 'px');
          overlay.style.setProperty('--darwin-overlay-y', event.clientY + 'px');
        });
        root.addEventListener('mouseleave', () => {
          overlay.style.setProperty('--darwin-overlay-x', '-999px');
          overlay.style.setProperty('--darwin-overlay-y', '-999px');
        });
        const trigger = document.createElement('div');
        trigger.id = 'darwin-cinema-trigger';
        Object.assign(trigger.style, {
          position: 'fixed', top: '0', right: '0', left: '0', height: '12px',
          zIndex: '2147483647', background: 'transparent'
        });
        trigger.addEventListener('mouseenter', () => console.info('__DARWIN_REVEAL_CHROME__'));
        root.appendChild(trigger);

        const corners = document.createElement('div');
        corners.id = 'darwin-cinema-corners';
        Object.assign(corners.style, {
          display: 'contents'
        });
        const cornerStyles = [
          { direction: 'nw', cursor: 'nwse-resize', top: '0', left: '0', borderTop: '1px solid', borderLeft: '1px solid', borderRadius: '14px 0 0 0' },
          { direction: 'ne', cursor: 'nesw-resize', top: '0', right: '0', borderTop: '1px solid', borderRight: '1px solid', borderRadius: '0 14px 0 0' },
          { direction: 'se', cursor: 'nwse-resize', bottom: '0', right: '0', borderBottom: '1px solid', borderRight: '1px solid', borderRadius: '0 0 14px 0' },
          { direction: 'sw', cursor: 'nesw-resize', bottom: '0', left: '0', borderBottom: '1px solid', borderLeft: '1px solid', borderRadius: '0 0 0 14px' }
        ];
        const reportResize = (phase, direction, event) => console.info(
          '__DARWIN_CINEMA_RESIZE__' + JSON.stringify({ phase, direction, x: event.screenX, y: event.screenY })
        );
        for (const { direction, cursor, ...placement } of cornerStyles) {
          const corner = document.createElement('span');
          Object.assign(corner.style, {
            position: 'fixed', zIndex: '2147483647', width: '22px', height: '22px',
            pointerEvents: 'auto', cursor, opacity: '0.38', touchAction: 'none',
            color: 'color-mix(in srgb, var(--darwin-overlay-color, #0c0c0d) 28%, #d8d4ca)',
            ...placement
          });
          corner.addEventListener('pointerdown', event => {
            if (event.button !== 0) return;
            event.preventDefault();
            corner.setPointerCapture(event.pointerId);
            reportResize('start', direction, event);
          });
          corner.addEventListener('pointermove', event => {
            if (corner.hasPointerCapture(event.pointerId)) reportResize('move', direction, event);
          });
          corner.addEventListener('pointerup', event => {
            if (!corner.hasPointerCapture(event.pointerId)) return;
            reportResize('end', direction, event);
            corner.releasePointerCapture(event.pointerId);
          });
          corner.addEventListener('pointercancel', event => reportResize('end', direction, event));
          corners.appendChild(corner);
        }
        root.appendChild(corners);
        return true;
      })()`)
    })
    contents.on('leave-html-full-screen', () => {
      this.#emit(request.instanceId, 'fullscreen-leave')
      void contents.executeJavaScript(
        "document.getElementById('darwin-cinema-overlay')?.remove(); document.getElementById('darwin-cinema-trigger')?.remove(); document.getElementById('darwin-cinema-corners')?.remove()"
      )
    })
    try {
      await contents.loadURL(request.url)
      return { ok: true }
    } catch {
      // Redirects can abort the original load while the replacement navigation continues.
      // did-fail-load is the authoritative source for user-visible failures.
      return { ok: contents.isLoading() }
    }
  }

  update(value: unknown) {
    const request = webAppUpdateSchema.parse(value)
    const hosted = this.#views.get(request.instanceId)
    if (!hosted) return { ok: false }
    hosted.bounds = request.bounds
    hosted.view.setBounds(
      request.keepAlive && !request.visible
        ? { x: -10_000, y: -10_000, width: 1, height: 1 }
        : request.bounds
    )
    hosted.view.setVisible(request.visible || request.keepAlive)
    void hosted.view.webContents.executeJavaScript(
      `document.documentElement.style.setProperty('--darwin-overlay-color', ${JSON.stringify(request.overlayColor)})`
    )
    if (request.focused && request.visible) {
      this.#window.contentView.removeChildView(hosted.view)
      this.#window.contentView.addChildView(hosted.view)
    }
    return { ok: true }
  }

  destroy(value: unknown) {
    const instanceId = webAppIdSchema.parse(value)
    const hosted = this.#views.get(instanceId)
    if (!hosted) return { ok: true }
    if (hosted.mediaTimer) clearInterval(hosted.mediaTimer)
    this.#emitMedia(instanceId, null)
    this.#window.contentView.removeChildView(hosted.view)
    hosted.view.webContents.close()
    this.#views.delete(instanceId)
    return { ok: true }
  }

  navigate(value: unknown) {
    const request = webAppNavigationSchema.parse(value)
    const contents = this.#views.get(request.instanceId)?.view.webContents
    if (!contents) return { ok: false }
    if (request.action === 'back' && contents.navigationHistory.canGoBack())
      contents.navigationHistory.goBack()
    if (request.action === 'forward' && contents.navigationHistory.canGoForward())
      contents.navigationHistory.goForward()
    if (request.action === 'reload') contents.reload()
    return { ok: true }
  }

  async controlMedia(value: unknown) {
    const action = mediaControlSchema.parse(value)
    const hosted = [...this.#views.values()].find(
      (candidate) => candidate.request.appId === 'darwin.youtube'
    )
    if (!hosted || hosted.view.webContents.isDestroyed()) return { ok: false }
    try {
      const handled = await hosted.view.webContents.executeJavaScript(
        youtubeMediaControlScript(action)
      )
      return { ok: Boolean(handled) }
    } catch {
      return { ok: false }
    }
  }

  setVoicePlaybackActive(active: boolean) {
    if (this.#voicePlaybackActive === active) return
    this.#voicePlaybackActive = active
    for (const hosted of this.#views.values()) {
      this.#setMediaDucked(hosted, active)
    }
  }

  #setMediaDucked(hosted: HostedView, ducked: boolean) {
    if (!hosted.request.permissions.includes('media.playback')) return
    const contents = hosted.view.webContents
    if (contents.isDestroyed()) return
    void contents
      .executeJavaScript(mediaDuckingScript(ducked, configuredMediaDuckRatio()))
      .catch(() => undefined)
  }

  destroyAll() {
    for (const id of [...this.#views.keys()]) this.destroy(id)
  }
}

export const registerWebAppHandlers = (window: BrowserWindow) => {
  const manager = new WebAppManager(window)
  ;['web-app:create', 'web-app:update', 'web-app:destroy', 'web-app:navigate', 'web-app:media-control'].forEach(
    (channel) => ipcMain.removeHandler(channel)
  )
  ipcMain.handle('web-app:create', async (_event, value) => {
    try {
      return await manager.create(value)
    } catch {
      return { ok: false }
    }
  })
  ipcMain.handle('web-app:update', (_event, value) => {
    try {
      return manager.update(value)
    } catch {
      return { ok: false }
    }
  })
  ipcMain.handle('web-app:destroy', (_event, value) => {
    try {
      return manager.destroy(value)
    } catch {
      return { ok: false }
    }
  })
  ipcMain.handle('web-app:navigate', (_event, value) => {
    try {
      return manager.navigate(value)
    } catch {
      return { ok: false }
    }
  })
  ipcMain.handle('web-app:media-control', async (_event, value) => {
    try {
      return await manager.controlMedia(value)
    } catch {
      return { ok: false }
    }
  })
  window.on('closed', () => manager.destroyAll())
  return manager
}

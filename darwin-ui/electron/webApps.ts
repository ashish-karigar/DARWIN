import { BrowserWindow, WebContentsView, ipcMain, shell } from 'electron'
import {
  isAllowedWebUrl,
  validateWebAppRequest,
  webAppIdSchema,
  webAppNavigationSchema,
  webAppUpdateSchema,
  type WebAppCreateRequest
} from './webSecurity.js'

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
}

export class WebAppManager {
  readonly #window: BrowserWindow
  readonly #views = new Map<string, HostedView>()

  constructor(window: BrowserWindow) {
    this.#window = window
  }

  #emit(instanceId: string, status: WebAppStatus, detail?: string) {
    this.#window.webContents.send('web-app:event', { instanceId, status, detail })
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
        autoplayPolicy: 'no-user-gesture-required'
      }
    })
    view.setBounds(request.bounds)
    view.setBackgroundColor('#000000')
    view.setVisible(false)
    this.#window.contentView.addChildView(view)
    this.#views.set(request.instanceId, {
      view,
      request,
      bounds: request.bounds
    })
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
          Object.assign(overlay.style, { position: 'fixed', inset: '0', zIndex: '2147483646', pointerEvents: 'none', background: 'linear-gradient(to bottom,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 96%,transparent) 4%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 55%,transparent) 11%,transparent 22%),linear-gradient(to top,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 96%,transparent) 4%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 55%,transparent) 11%,transparent 22%),linear-gradient(to right,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 50%,transparent) 11%,transparent 22%),linear-gradient(to left,var(--darwin-overlay-color,#0c0c0d) 0%,color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 50%,transparent) 11%,transparent 22%)', boxShadow: 'inset 0 0 7.5rem 2.75rem color-mix(in srgb,var(--darwin-overlay-color,#0c0c0d) 82%,transparent)', webkitMaskImage: 'radial-gradient(circle 7rem at var(--darwin-clear-x,-999px) var(--darwin-clear-y,-999px),rgb(0 0 0 / 28%) 0%,rgb(0 0 0 / 52%) 42%,#000 100%)', maskImage: 'radial-gradient(circle 7rem at var(--darwin-clear-x,-999px) var(--darwin-clear-y,-999px),rgb(0 0 0 / 28%) 0%,rgb(0 0 0 / 52%) 42%,#000 100%)' });
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

  destroyAll() {
    for (const id of [...this.#views.keys()]) this.destroy(id)
  }
}

export const registerWebAppHandlers = (window: BrowserWindow) => {
  const manager = new WebAppManager(window)
  ;['web-app:create', 'web-app:update', 'web-app:destroy', 'web-app:navigate'].forEach(
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
  window.on('closed', () => manager.destroyAll())
}

import { app, BrowserWindow, session, shell } from 'electron'
import { join } from 'node:path'
import { registerCredentialHandlers } from './credentials.js'
import { registerWebAppHandlers } from './webApps.js'
import { registerReminderHandlers } from './reminders.js'
import { registerAssistantStateService } from './assistantState.js'

const isAllowedExternalUrl = (url: string): boolean => {
  try {
    const parsedUrl = new URL(url)
    return parsedUrl.protocol === 'https:'
  } catch {
    return false
  }
}

const createMainWindow = (): BrowserWindow => {
  const window = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    show: false,
    backgroundColor: '#070b14',
    title: 'DARWIN',
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })
  registerWebAppHandlers(window)
  registerAssistantStateService(window)

  window.webContents.on('preload-error', (_event, preloadPath, error) => {
    console.error(`DARWIN preload failed: ${preloadPath}`, error)
  })

  window.once('ready-to-show', () => window.show())

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedExternalUrl(url)) {
      void shell.openExternal(url)
    }
    return { action: 'deny' }
  })

  if (process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    void window.loadFile(join(__dirname, '../renderer/index.html'))
  }

  return window
}

app.whenReady().then(() => {
  session.defaultSession.setPermissionCheckHandler(
    (_webContents, permission) => permission === 'media'
  )
  session.defaultSession.setPermissionRequestHandler(
    (_webContents, permission, callback, details) => {
      const shellMedia =
        permission === 'media' &&
        (!('mediaTypes' in details) ||
          !details.mediaTypes ||
          details.mediaTypes.every((type) => type === 'video' || type === 'audio'))
      callback(shellMedia)
    }
  )
  registerCredentialHandlers()
  registerReminderHandlers()
  createMainWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

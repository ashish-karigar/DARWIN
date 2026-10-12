import { useEffect, useState } from 'react'
import { SettingsApp } from './apps/native/SettingsApp'
import { AppLauncher } from './shell/AppLauncher'
import { Dock } from './shell/Dock'
import { StatusBar } from './shell/StatusBar'
import { Workspace } from './shell/Workspace'
import { shellApps, type ShellApp } from './shell/apps'
import { useShellKeyboard } from './shell/useShellKeyboard'
import { useWindowStore } from './stores/windowStore'
import { useSettingsStore } from './stores/settingsStore'
import { useAssistantStore } from './stores/assistantStore'
import { useConversationStore } from './stores/conversationStore'
import { SystemStats } from './shell/SystemStats'
import { NowPlaying } from './shell/NowPlaying'
import { serverMessageSchema } from '../shared/contracts'
import { CalendarWidget } from './shell/CalendarWidget'

export function App() {
  const connectAssistant = useAssistantStore((state) => state.connect)
  const connectConversation = useConversationStore((state) => state.connect)
  const themePreference = useSettingsStore((state) => state.theme)
  const setThemePreference = useSettingsStore((state) => state.setTheme)
  const onboardingComplete = useSettingsStore((state) => state.onboardingComplete)
  const theme = themePreference === 'projector' ? 'projector' : 'dark'
  const [launcherOpen, setLauncherOpen] = useState(false)
  const [fullscreenApp, setFullscreenApp] = useState<ShellApp | null>(() =>
    onboardingComplete
      ? null
      : (shellApps.find((app) => app.id === 'darwin.settings') ?? null)
  )
  const windows = useWindowStore((state) => state.windows)
  const focusedWindowId = useWindowStore((state) => state.focusedWindowId)
  const openWindow = useWindowStore((state) => state.openWindow)
  const minimizeWindow = useWindowStore((state) => state.minimizeWindow)
  const closeWindow = useWindowStore((state) => state.closeWindow)
  const focusedWindow = windows.find((window) => window.instanceId === focusedWindowId)
  const activeApp =
    fullscreenApp ?? shellApps.find((app) => app.id === focusedWindow?.appId) ?? null
  const runningAppIds = [
    ...windows.map((window) => window.appId),
    ...(fullscreenApp ? [fullscreenApp.id] : [])
  ]

  useEffect(() => connectAssistant(), [connectAssistant])
  useEffect(() => connectConversation(), [connectConversation])

  useEffect(() => {
    const session = window.darwinAssistantSession
    if (!session) return
    const subscription = session.subscribeEvents((value) => {
      const parsed = serverMessageSchema.safeParse(value)
      if (parsed.success && parsed.data.type === 'app.command') {
        const command = parsed.data
        const app = shellApps.find((candidate) => candidate.id === command.appId)
        if (!app) return
        const existing = useWindowStore.getState().windows.find((item) => item.appId === app.id)
        if (parsed.data.action === 'close') {
          if (existing) closeWindow(existing.instanceId)
          setFullscreenApp((current) => current?.id === app.id ? null : current)
        } else if (app.displayMode === 'fullscreen') {
          setFullscreenApp(app)
        } else {
          openWindow({ appId: app.id, title: app.name, bounds: { x: 120, y: 92, width: 720, height: 480 }, instancePolicy: app.instancePolicy })
        }
        return
      }
      if (!parsed.success || parsed.data.type !== 'camera.command') return
      const camera = shellApps.find((app) => app.id === 'darwin.camera')
      if (!camera) return
      const action = parsed.data.action
      const existing = useWindowStore
        .getState()
        .windows.find((managedWindow) => managedWindow.appId === camera.id)
      if (action === 'close') {
        if (existing) closeWindow(existing.instanceId)
        return
      }
      if (!existing || action === 'open') {
        const offset = Math.min(useWindowStore.getState().windows.length * 24, 120)
        openWindow({
          appId: camera.id,
          title: camera.name,
          bounds: { x: 120 + offset, y: 92 + offset, width: 720, height: 480 },
          instancePolicy: camera.instancePolicy
        })
      }
      if (action !== 'open') {
        window.setTimeout(
          () =>
            window.dispatchEvent(
              new CustomEvent('darwin:camera-command', { detail: { action } })
            ),
          0
        )
      }
    })
    return () => session.unsubscribe(subscription)
  }, [closeWindow, openWindow])

  const launchApp = (app: ShellApp) => {
    if (app.displayMode === 'fullscreen') {
      setLauncherOpen(false)
      setFullscreenApp((current) => (current?.id === app.id ? null : app))
      return
    }
    const existing = windows.find((window) => window.appId === app.id)
    if (existing?.focused && existing.mode !== 'minimized') {
      minimizeWindow(existing.instanceId)
      return
    }
    const offset = Math.min(windows.length * 24, 120)
    openWindow({
      appId: app.id,
      title: app.name,
      bounds: { x: 120 + offset, y: 92 + offset, width: 720, height: 480 },
      instancePolicy: app.instancePolicy
    })
  }

  useShellKeyboard({
    launcherOpen,
    onCloseLauncher: () => setLauncherOpen(false),
    onOpenAssistant: () => {
      window.dispatchEvent(new Event('darwin:focus-transcript'))
    },
    onToggleLauncher: () => setLauncherOpen((open) => !open)
  })

  return (
    <main className="darwin-shell" data-theme={theme}>
      <StatusBar
        theme={theme}
        onToggleTheme={() => setThemePreference(theme === 'dark' ? 'projector' : 'dark')}
      />
      {!fullscreenApp && (
        <>
          <SystemStats />
          <NowPlaying />
          <CalendarWidget
            onOpen={() => {
              const calendar = shellApps.find((app) => app.id === 'darwin.calendar')
              if (calendar) launchApp(calendar)
            }}
          />
        </>
      )}
      <Workspace suspended={Boolean(fullscreenApp)} />
      <Dock
        apps={shellApps}
        activeAppId={activeApp?.id ?? null}
        runningAppIds={runningAppIds}
        onLaunchApp={launchApp}
        onOpenLauncher={() => setLauncherOpen(true)}
      />
      <AppLauncher
        apps={shellApps}
        open={launcherOpen}
        onClose={() => setLauncherOpen(false)}
        onLaunchApp={launchApp}
      />
      {fullscreenApp?.id === 'darwin.settings' && (
        <SettingsApp onClose={() => setFullscreenApp(null)} />
      )}
    </main>
  )
}

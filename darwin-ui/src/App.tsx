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

export function App() {
  const connectAssistant = useAssistantStore((state) => state.connect)
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
  const focusedWindow = windows.find((window) => window.instanceId === focusedWindowId)
  const activeApp =
    fullscreenApp ?? shellApps.find((app) => app.id === focusedWindow?.appId) ?? null
  const runningAppIds = [
    ...windows.map((window) => window.appId),
    ...(fullscreenApp ? [fullscreenApp.id] : [])
  ]

  useEffect(() => connectAssistant(), [connectAssistant])

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
      const assistant = shellApps.find((app) => app.id === 'darwin.assistant')
      if (assistant) launchApp(assistant)
    },
    onToggleLauncher: () => setLauncherOpen((open) => !open)
  })

  return (
    <main className="darwin-shell" data-theme={theme}>
      <StatusBar
        theme={theme}
        onToggleTheme={() => setThemePreference(theme === 'dark' ? 'projector' : 'dark')}
      />
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

import { useMemo, type ComponentType } from 'react'
import type { AppManifest, WindowBounds } from '../../../shared/contracts'
import type { ManagedWindow } from '../../stores/windowStore'
import { useWindowStore } from '../../stores/windowStore'
import { AssistantApp } from './AssistantApp'
import { NativeAppProvider, type NativeAppContextValue } from './NativeAppContext'
import { NativeAppErrorBoundary } from './NativeAppErrorBoundary'
import { SettingsApp } from './SettingsApp'
import { RemindersApp } from './RemindersApp'
import { CameraApp } from './CameraApp'

const nativeApps: Readonly<Record<string, ComponentType>> = {
  assistant: AssistantApp,
  camera: CameraApp,
  reminders: RemindersApp,
  settings: SettingsApp
}

interface NativeAppHostProps {
  manifest: AppManifest
  managedWindow: ManagedWindow
  workspace: WindowBounds
  componentOverride?: ComponentType
  onCommand?: (instanceId: string, command: string, payload?: unknown) => boolean
}

export function NativeAppHost({
  componentOverride,
  managedWindow,
  manifest,
  onCommand,
  workspace
}: NativeAppHostProps) {
  const closeWindow = useWindowStore((state) => state.closeWindow)
  const maximizeWindow = useWindowStore((state) => state.maximizeWindow)
  const minimizeWindow = useWindowStore((state) => state.minimizeWindow)
  const restoreWindow = useWindowStore((state) => state.restoreWindow)
  const AppComponent =
    componentOverride ?? (manifest.entry ? nativeApps[manifest.entry] : undefined)
  const context = useMemo<NativeAppContextValue>(
    () => ({
      instanceId: managedWindow.instanceId,
      manifest,
      window: {
        bounds: managedWindow.bounds,
        mode: managedWindow.mode,
        close: () => closeWindow(managedWindow.instanceId),
        minimize: () => minimizeWindow(managedWindow.instanceId),
        maximize: () => maximizeWindow(managedWindow.instanceId, workspace),
        restore: () => restoreWindow(managedWindow.instanceId)
      },
      permissions: {
        has: (permission) => manifest.permissions.includes(permission),
        list: () => manifest.permissions
      },
      commands: {
        dispatch: (command, payload) =>
          onCommand?.(managedWindow.instanceId, command, payload) ?? false
      }
    }),
    [
      closeWindow,
      managedWindow.bounds,
      managedWindow.instanceId,
      managedWindow.mode,
      manifest,
      maximizeWindow,
      minimizeWindow,
      onCommand,
      restoreWindow,
      workspace
    ]
  )

  if (!AppComponent) {
    return (
      <div className="native-app-error" role="alert">
        <strong>{manifest.name} cannot be opened.</strong>
        <p>Native entry “{manifest.entry ?? 'missing'}” is not registered.</p>
      </div>
    )
  }

  return (
    <NativeAppErrorBoundary appName={manifest.name}>
      <NativeAppProvider value={context}>
        <AppComponent />
      </NativeAppProvider>
    </NativeAppErrorBoundary>
  )
}

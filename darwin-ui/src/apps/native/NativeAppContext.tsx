import { createContext, useContext, type ReactNode } from 'react'
import type { AppManifest, WindowBounds } from '../../../shared/contracts'

export interface NativeAppWindowControls {
  close: () => void
  minimize: () => void
  maximize: () => void
  restore: () => void
  bounds: WindowBounds
  mode: 'normal' | 'minimized' | 'maximized'
}

export interface NativeAppCommandBus {
  dispatch: (command: string, payload?: unknown) => boolean
}

export interface NativeAppContextValue {
  instanceId: string
  manifest: AppManifest
  window: NativeAppWindowControls
  permissions: {
    has: (permission: string) => boolean
    list: () => readonly string[]
  }
  commands: NativeAppCommandBus
}

const NativeAppContext = createContext<NativeAppContextValue | null>(null)

export function NativeAppProvider({
  children,
  value
}: {
  children: ReactNode
  value: NativeAppContextValue
}) {
  return <NativeAppContext.Provider value={value}>{children}</NativeAppContext.Provider>
}

// This hook intentionally shares the provider's private context.
// eslint-disable-next-line react-refresh/only-export-components
export function useNativeApp(): NativeAppContextValue {
  const context = useContext(NativeAppContext)
  if (!context) throw new Error('useNativeApp must be used inside a NativeAppProvider.')
  return context
}

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AppManifest } from '../../../shared/contracts'
import type { ManagedWindow } from '../../stores/windowStore'
import { useWindowStore } from '../../stores/windowStore'
import { appRegistry } from '../registry'
import { useNativeApp } from './NativeAppContext'
import { NativeAppHost } from './NativeAppHost'

const workspace = { x: 0, y: 44, width: 1280, height: 676 }
const settingsManifest = appRegistry.get('darwin.settings')!
const assistantManifest = appRegistry.get('darwin.assistant')!

const managedWindow: ManagedWindow = {
  appId: settingsManifest.id,
  bounds: { x: 120, y: 92, width: 720, height: 480 },
  focused: true,
  instanceId: '6f6bbfd0-dde9-4c27-9234-7f8156631d7a',
  mode: 'normal',
  restoreBounds: null,
  title: settingsManifest.name,
  zIndex: 1
}

describe('NativeAppHost', () => {
  beforeEach(() => useWindowStore.getState().reset())

  it('maps a registered native entry to its application component', () => {
    render(
      <NativeAppHost
        manifest={assistantManifest}
        managedWindow={managedWindow}
        workspace={workspace}
      />
    )
    expect(screen.getByRole('heading', { name: 'Not connected' })).toBeInTheDocument()
  })

  it('provides scoped instance, permission, and command context', () => {
    const onCommand = vi.fn(() => true)
    function Inspector() {
      const app = useNativeApp()
      return (
        <button type="button" onClick={() => app.commands.dispatch('inspect')}>
          {app.instanceId}:{String(app.permissions.has('preferences.read'))}
        </button>
      )
    }

    render(
      <NativeAppHost
        componentOverride={Inspector}
        manifest={settingsManifest}
        managedWindow={managedWindow}
        workspace={workspace}
        onCommand={onCommand}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /true/ }))
    expect(onCommand).toHaveBeenCalledWith(managedWindow.instanceId, 'inspect', undefined)
  })

  it('renders a recoverable error for an unknown native entry', () => {
    const unknownManifest: AppManifest = { ...settingsManifest, entry: 'not-registered' }
    render(
      <NativeAppHost
        manifest={unknownManifest}
        managedWindow={managedWindow}
        workspace={workspace}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('cannot be opened')
  })

  it('contains a component crash and can reload the app', () => {
    let shouldCrash = true
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    function RecoverableApp() {
      if (shouldCrash) throw new Error('test crash')
      return <p>Recovered application</p>
    }

    render(
      <NativeAppHost
        componentOverride={RecoverableApp}
        manifest={settingsManifest}
        managedWindow={managedWindow}
        workspace={workspace}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('stopped unexpectedly')
    shouldCrash = false
    fireEvent.click(screen.getByRole('button', { name: 'Reload app' }))
    expect(screen.getByText('Recovered application')).toBeInTheDocument()
    consoleError.mockRestore()
  })

  it('keeps another native app rendered when one app crashes', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    function BrokenApp(): never {
      throw new Error('isolated crash')
    }
    function HealthyApp() {
      return <p>Healthy application</p>
    }

    render(
      <>
        <NativeAppHost
          componentOverride={BrokenApp}
          manifest={settingsManifest}
          managedWindow={managedWindow}
          workspace={workspace}
        />
        <NativeAppHost
          componentOverride={HealthyApp}
          manifest={settingsManifest}
          managedWindow={{
            ...managedWindow,
            instanceId: '0fea0907-a656-409b-863b-3c87f2294509'
          }}
          workspace={workspace}
        />
      </>
    )

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('Healthy application')).toBeInTheDocument()
    consoleError.mockRestore()
  })
})

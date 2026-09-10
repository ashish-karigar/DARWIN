import '@testing-library/jest-dom/vitest'
import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AppManifest } from '../../../shared/contracts'
import { WebAppHost } from './WebAppHost'

const create = vi.fn(async () => ({ ok: true }))
const update = vi.fn(async () => ({ ok: true }))
const destroy = vi.fn(async () => ({ ok: true }))
let statusListener: (event: unknown) => void = () => undefined

const manifest: AppManifest = {
  id: 'darwin.youtube',
  name: 'YouTube',
  description: '',
  version: '1',
  type: 'web',
  url: 'https://www.youtube.com',
  allowedOrigins: ['https://www.youtube.com'],
  permissions: [],
  session: 'darwin.youtube',
  instancePolicy: 'single',
  pinned: true,
  launcherOrder: 1,
  displayMode: 'window',
  windowStyle: 'frameless',
  edgeEffect: 'flow'
}
const managedWindow = {
  instanceId: '11111111-1111-4111-8111-111111111111',
  appId: 'darwin.youtube',
  title: 'YouTube',
  bounds: { x: 100, y: 90, width: 720, height: 480 },
  restoreBounds: null,
  mode: 'normal' as const,
  focused: true,
  zIndex: 1
}

describe('WebAppHost', () => {
  beforeEach(() => {
    create.mockClear()
    update.mockClear()
    destroy.mockClear()
    Object.defineProperty(window, 'darwinHost', {
      configurable: true,
      value: {
        versions: { chrome: '1', electron: '1', node: '1' },
        credentials: {}
      }
    })
    Object.defineProperty(window, 'darwinWebApps', {
      configurable: true,
      value: {
        create,
        update,
        destroy,
        subscribeStatus: (listener: typeof statusListener) => {
          statusListener = listener
          return 'test-subscription'
        },
        unsubscribeStatus: () => undefined
      }
    })
  })

  it('creates, positions, reveals, and destroys a hosted view', async () => {
    const result = render(
      <WebAppHost manifest={manifest} managedWindow={managedWindow} interacting={false} />
    )
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        appId: 'darwin.youtube',
        bounds: { x: 0, y: 0, width: 1, height: 1 }
      })
    )
    expect(update).toHaveBeenCalledWith(
      expect.objectContaining({ bounds: { x: 110, y: 100, width: 700, height: 460 } })
    )
    act(() => statusListener({ instanceId: managedWindow.instanceId, status: 'ready' }))
    expect(update).toHaveBeenLastCalledWith(
      expect.objectContaining({ visible: true, focused: true })
    )
    act(() => statusListener({ instanceId: managedWindow.instanceId, status: 'loading' }))
    expect(result.container.querySelector('.web-app-underlay')).toBeInTheDocument()
    result.unmount()
    expect(destroy).toHaveBeenCalledWith(managedWindow.instanceId)
  })

  it('renders a safe fallback without the host bridge', () => {
    Object.defineProperty(window, 'darwinWebApps', {
      configurable: true,
      value: undefined
    })
    render(
      <WebAppHost manifest={manifest} managedWindow={managedWindow} interacting={false} />
    )
    expect(screen.getByText('Web host unavailable')).toBeInTheDocument()
  })

  it('keeps the same hosted view alive while minimized', () => {
    const result = render(
      <WebAppHost manifest={manifest} managedWindow={managedWindow} interacting={false} />
    )
    result.rerender(
      <WebAppHost
        manifest={manifest}
        managedWindow={{ ...managedWindow, mode: 'minimized', focused: false }}
        interacting={false}
      />
    )
    expect(create).toHaveBeenCalledTimes(1)
    expect(destroy).not.toHaveBeenCalled()
    expect(update).toHaveBeenLastCalledWith(
      expect.objectContaining({ visible: false, keepAlive: true })
    )
  })

  it('keeps a ready floating web app visible when focus moves elsewhere', () => {
    const result = render(
      <WebAppHost manifest={manifest} managedWindow={managedWindow} interacting={false} />
    )
    act(() => statusListener({ instanceId: managedWindow.instanceId, status: 'ready' }))
    result.rerender(
      <WebAppHost
        manifest={manifest}
        managedWindow={{ ...managedWindow, focused: false }}
        interacting={false}
      />
    )
    expect(update).toHaveBeenLastCalledWith(
      expect.objectContaining({ visible: true, focused: false })
    )
  })
})

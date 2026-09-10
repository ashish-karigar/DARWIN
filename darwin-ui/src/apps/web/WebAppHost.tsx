import { useEffect, useState } from 'react'
import { z } from 'zod'
import type { AppManifest } from '../../../shared/contracts'
import type { ManagedWindow } from '../../stores/windowStore'
import { useSettingsStore } from '../../stores/settingsStore'

const statusEventSchema = z.object({
  instanceId: z.string().uuid(),
  status: z.enum([
    'loading',
    'ready',
    'offline',
    'certificate-error',
    'crashed',
    'error',
    'fullscreen-enter',
    'fullscreen-leave',
    'chrome-reveal',
    'cinema-resize'
  ]),
  detail: z.string().optional()
})
type WebStatus = Exclude<
  z.infer<typeof statusEventSchema>['status'],
  'fullscreen-enter' | 'fullscreen-leave' | 'chrome-reveal' | 'cinema-resize'
>

const cinemaResizeEventSchema = z.object({
  phase: z.enum(['start', 'move', 'end']),
  direction: z.enum(['nw', 'ne', 'se', 'sw']),
  x: z.number(),
  y: z.number()
})
export type CinemaResizeEvent = z.infer<typeof cinemaResizeEventSchema>

interface WebAppHostProps {
  manifest: AppManifest
  managedWindow: ManagedWindow
  interacting: boolean
  suspended?: boolean
  cinemaMode?: boolean
  chromeRevealed?: boolean
  onCinemaModeChange?: (enabled: boolean) => void
  onChromeReveal?: () => void
  onCinemaResize?: (event: CinemaResizeEvent) => void
}

const contentBounds = (
  window: ManagedWindow,
  chromeRevealed: boolean,
  cinemaMode: boolean
) => {
  const gutter = cinemaMode ? 0 : 10
  const top = chromeRevealed ? 36 : gutter
  return {
    x: Math.round(window.bounds.x + gutter),
    y: Math.round(window.bounds.y + top),
    width: Math.max(1, Math.round(window.bounds.width - gutter * 2)),
    height: Math.max(1, Math.round(window.bounds.height - top - gutter))
  }
}

export function WebAppHost({
  manifest,
  managedWindow,
  interacting,
  suspended = false,
  cinemaMode = false,
  chromeRevealed = false,
  onCinemaModeChange,
  onChromeReveal,
  onCinemaResize
}: WebAppHostProps) {
  const [status, setStatus] = useState<WebStatus>('loading')
  const bridge = window.darwinWebApps
  const instanceId = managedWindow.instanceId
  const theme = useSettingsStore((state) => state.theme)

  useEffect(() => {
    if (!bridge || !manifest.url || !manifest.session) return
    void bridge
      .create({
        instanceId,
        appId: manifest.id,
        url: manifest.url,
        allowedOrigins: manifest.allowedOrigins,
        permissions: manifest.permissions,
        session: manifest.session,
        bounds: { x: 0, y: 0, width: 1, height: 1 },
        edgeEffect: manifest.edgeEffect
      })
      .then((result) => {
        if (result.ok) setStatus('ready')
      })
      .catch(() => setStatus('error'))
    return () => {
      void bridge.destroy(instanceId)
    }
  }, [bridge, instanceId, manifest])

  useEffect(() => {
    if (!bridge) return
    const subscriptionId = bridge.subscribeStatus((value) => {
      const result = statusEventSchema.safeParse(value)
      if (result.success && result.data.instanceId === managedWindow.instanceId) {
        if (result.data.status === 'fullscreen-enter') return onCinemaModeChange?.(true)
        if (result.data.status === 'fullscreen-leave') return onCinemaModeChange?.(false)
        if (result.data.status === 'chrome-reveal') return onChromeReveal?.()
        if (result.data.status === 'cinema-resize' && result.data.detail) {
          try {
            const resize = cinemaResizeEventSchema.safeParse(
              JSON.parse(result.data.detail) as unknown
            )
            if (resize.success) onCinemaResize?.(resize.data)
          } catch {
            // Ignore malformed messages from hosted web content.
          }
          return
        }
        const nextStatus = result.data.status as WebStatus
        setStatus((current) =>
          nextStatus === 'loading' && current === 'ready' ? current : nextStatus
        )
      }
    })
    return () => bridge.unsubscribeStatus(subscriptionId)
  }, [
    bridge,
    managedWindow.instanceId,
    onChromeReveal,
    onCinemaModeChange,
    onCinemaResize
  ])

  useEffect(() => {
    if (!bridge) return
    void bridge.update({
      instanceId: managedWindow.instanceId,
      bounds: contentBounds(managedWindow, chromeRevealed, cinemaMode),
      visible: managedWindow.mode !== 'minimized' && !suspended && status === 'ready',
      keepAlive: managedWindow.mode === 'minimized',
      focused: managedWindow.focused,
      overlayColor: theme === 'projector' ? '#000000' : '#0c0c0d'
    })
  }, [
    bridge,
    chromeRevealed,
    cinemaMode,
    interacting,
    managedWindow,
    status,
    suspended,
    theme
  ])

  if (!bridge)
    return (
      <WebAppState
        title="Web host unavailable"
        detail="Restart DARWIN to load this application."
      />
    )
  if (status === 'ready') return <div className="web-app-underlay" aria-hidden="true" />
  const copy: Record<Exclude<WebStatus, 'ready'>, [string, string]> = {
    loading: ['Loading', `Opening ${manifest.name}…`],
    offline: [
      'You appear to be offline',
      'Check the network connection and reopen the application.'
    ],
    'certificate-error': [
      'Connection blocked',
      'DARWIN rejected an invalid security certificate.'
    ],
    crashed: ['Application stopped', 'Close this window and open the application again.'],
    error: ['Could not open application', 'The page failed to load. Try again later.']
  }
  const [title, detail] = copy[status]
  return <WebAppState title={title} detail={detail} />
}

function WebAppState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="web-app-state">
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  )
}

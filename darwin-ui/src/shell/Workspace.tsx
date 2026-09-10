import { useEffect, useRef, useState } from 'react'
import type { WindowBounds } from '../../shared/contracts'
import { NativeAppHost } from '../apps/native/NativeAppHost'
import { WebAppHost } from '../apps/web/WebAppHost'
import { useWindowStore } from '../stores/windowStore'
import { shellApps } from './apps'
import { WindowFrame } from './WindowFrame'
import { NeuralCore } from './NeuralCore'
import { resizedBounds, type ResizeDirection } from './windowGeometry'

const STATUS_BAR_HEIGHT = 44

const readWorkspace = (): WindowBounds => ({
  x: 0,
  y: STATUS_BAR_HEIGHT,
  width: window.innerWidth,
  height: Math.max(window.innerHeight - STATUS_BAR_HEIGHT, 200)
})

export function Workspace({ suspended = false }: { suspended?: boolean }) {
  const windows = useWindowStore((state) => state.windows)
  const maximizeWindow = useWindowStore((state) => state.maximizeWindow)
  const resizeCinemaWindow = useWindowStore((state) => state.resizeCinemaWindow)
  const cinemaResizeSessions = useRef(
    new Map<
      string,
      { x: number; y: number; bounds: WindowBounds; direction: ResizeDirection }
    >()
  )
  const [workspace, setWorkspace] = useState(readWorkspace)
  const [interactingWindows, setInteractingWindows] = useState<Set<string>>(
    () => new Set()
  )
  const [cinemaWindows, setCinemaWindows] = useState<Set<string>>(() => new Set())
  const [revealedChrome, setRevealedChrome] = useState<Set<string>>(() => new Set())
  const updateSet = (
    setter: React.Dispatch<React.SetStateAction<Set<string>>>,
    id: string,
    enabled: boolean
  ) =>
    setter((current) => {
      const next = new Set(current)
      if (enabled) next.add(id)
      else next.delete(id)
      return next
    })

  useEffect(() => {
    const handleResize = () => {
      const nextWorkspace = readWorkspace()
      setWorkspace(nextWorkspace)
      useWindowStore
        .getState()
        .windows.filter((managedWindow) => managedWindow.mode === 'maximized')
        .forEach((managedWindow) =>
          maximizeWindow(managedWindow.instanceId, nextWorkspace)
        )
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [maximizeWindow])

  return (
    <section className="workspace" aria-label="Desktop workspace">
      <NeuralCore />
      {windows.map((managedWindow) => {
        const app = shellApps.find((candidate) => candidate.id === managedWindow.appId)
        return app ? (
          <WindowFrame
            key={managedWindow.instanceId}
            app={app}
            window={managedWindow}
            workspace={workspace}
            onInteractionChange={(interacting) =>
              setInteractingWindows((current) => {
                const next = new Set(current)
                if (interacting) next.add(managedWindow.instanceId)
                else next.delete(managedWindow.instanceId)
                return next
              })
            }
            cinemaMode={cinemaWindows.has(managedWindow.instanceId)}
            chromeRevealed={revealedChrome.has(managedWindow.instanceId)}
            onChromeRevealChange={(visible) =>
              updateSet(setRevealedChrome, managedWindow.instanceId, visible)
            }
          >
            {app.manifest.type === 'native' ? (
              <NativeAppHost
                manifest={app.manifest}
                managedWindow={managedWindow}
                workspace={workspace}
              />
            ) : undefined}
            {app.manifest.type === 'web' ? (
              <WebAppHost
                manifest={app.manifest}
                managedWindow={managedWindow}
                interacting={interactingWindows.has(managedWindow.instanceId)}
                suspended={suspended}
                cinemaMode={cinemaWindows.has(managedWindow.instanceId)}
                chromeRevealed={revealedChrome.has(managedWindow.instanceId)}
                onCinemaModeChange={(enabled) => {
                  updateSet(setCinemaWindows, managedWindow.instanceId, enabled)
                  if (!enabled)
                    updateSet(setRevealedChrome, managedWindow.instanceId, false)
                }}
                onChromeReveal={() =>
                  updateSet(setRevealedChrome, managedWindow.instanceId, true)
                }
                onCinemaResize={(event) => {
                  if (event.phase === 'start') {
                    cinemaResizeSessions.current.set(managedWindow.instanceId, {
                      x: event.x,
                      y: event.y,
                      bounds: { ...managedWindow.bounds },
                      direction: event.direction
                    })
                    return
                  }
                  const session = cinemaResizeSessions.current.get(
                    managedWindow.instanceId
                  )
                  if (!session) return
                  if (event.phase === 'move')
                    resizeCinemaWindow(
                      managedWindow.instanceId,
                      resizedBounds(
                        session.bounds,
                        session.direction,
                        event.x - session.x,
                        event.y - session.y
                      ),
                      workspace
                    )
                  if (event.phase === 'end')
                    cinemaResizeSessions.current.delete(managedWindow.instanceId)
                }}
              />
            ) : undefined}
          </WindowFrame>
        ) : null
      })}
    </section>
  )
}

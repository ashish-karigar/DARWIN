import {
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode
} from 'react'
import type { WindowBounds } from '../../shared/contracts'
import type { ManagedWindow } from '../stores/windowStore'
import { useWindowStore } from '../stores/windowStore'
import type { ShellApp } from './apps'
import { resizedBounds, type ResizeDirection } from './windowGeometry'

interface WindowFrameProps {
  app: ShellApp
  window: ManagedWindow
  workspace: WindowBounds
  children?: ReactNode
  onInteractionChange?: (interacting: boolean) => void
  cinemaMode?: boolean
  chromeRevealed?: boolean
  onChromeRevealChange?: (visible: boolean) => void
}

interface PointerSession {
  pointerId: number
  startX: number
  startY: number
  bounds: WindowBounds
}

const resizeDirections: ResizeDirection[] = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw']

export function WindowFrame({
  app,
  children,
  cinemaMode = false,
  chromeRevealed = false,
  onChromeRevealChange,
  onInteractionChange,
  window: managedWindow,
  workspace
}: WindowFrameProps) {
  const focusWindow = useWindowStore((state) => state.focusWindow)
  const moveWindow = useWindowStore((state) => state.moveWindow)
  const resizeWindow = useWindowStore((state) => state.resizeWindow)
  const minimizeWindow = useWindowStore((state) => state.minimizeWindow)
  const maximizeWindow = useWindowStore((state) => state.maximizeWindow)
  const restoreWindow = useWindowStore((state) => state.restoreWindow)
  const closeWindow = useWindowStore((state) => state.closeWindow)
  const pointerSession = useRef<PointerSession | null>(null)
  const chromeActive = useRef(false)
  const [interacting, setInteracting] = useState(false)

  const beginPointerSession = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0 || managedWindow.mode !== 'normal') return false
    event.preventDefault()
    event.stopPropagation()
    focusWindow(managedWindow.instanceId)
    event.currentTarget.setPointerCapture(event.pointerId)
    pointerSession.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      bounds: { ...managedWindow.bounds }
    }
    setInteracting(true)
    onInteractionChange?.(true)
    return true
  }

  const finishPointerSession = (event: ReactPointerEvent<HTMLElement>) => {
    if (pointerSession.current?.pointerId !== event.pointerId) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    pointerSession.current = null
    setInteracting(false)
    onInteractionChange?.(false)
  }

  const toggleMaximize = () => {
    if (managedWindow.mode === 'maximized') restoreWindow(managedWindow.instanceId)
    else maximizeWindow(managedWindow.instanceId, workspace)
  }

  return (
    <article
      className="window-frame"
      data-focused={managedWindow.focused}
      data-interacting={interacting}
      data-mode={managedWindow.mode}
      data-cinema={cinemaMode}
      data-chrome-revealed={chromeRevealed}
      data-window-style={app.manifest.windowStyle}
      aria-label={`${managedWindow.title} window`}
      style={{
        display: managedWindow.mode === 'minimized' ? 'none' : undefined,
        left: managedWindow.bounds.x,
        top: managedWindow.bounds.y,
        width: managedWindow.bounds.width,
        height: managedWindow.bounds.height,
        zIndex: managedWindow.zIndex
      }}
      onPointerDown={() => focusWindow(managedWindow.instanceId)}
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect()
        if (app.manifest.edgeEffect === 'flow' && app.manifest.type !== 'web') {
          event.currentTarget.style.setProperty(
            '--overlay-clear-x',
            `${event.clientX - rect.left}px`
          )
          event.currentTarget.style.setProperty(
            '--overlay-clear-y',
            `${event.clientY - rect.top}px`
          )
        }
        if (app.manifest.type === 'web') return
        const depth = (event.clientY - rect.top) / rect.height
        const strength = Math.max(0, Math.min(1, 1 - depth / 0.3))
        event.currentTarget.style.setProperty('--chrome-reveal', String(strength))
        const active = strength > 0
        if (active !== chromeActive.current) {
          chromeActive.current = active
          onChromeRevealChange?.(active)
        }
      }}
      onPointerLeave={(event) => {
        event.currentTarget.style.setProperty('--overlay-clear-x', '-999px')
        event.currentTarget.style.setProperty('--overlay-clear-y', '-999px')
        if (app.manifest.type === 'web') return
        event.currentTarget.style.setProperty('--chrome-reveal', '0')
        if (chromeActive.current) {
          chromeActive.current = false
          onChromeRevealChange?.(false)
        }
      }}
    >
      {app.manifest.type === 'web' && (
        <span
          className="window-frame__cinema-trigger"
          aria-hidden="true"
          onPointerEnter={() => onChromeRevealChange?.(true)}
        />
      )}
      <header
        className="window-frame__titlebar"
        onDoubleClick={toggleMaximize}
        onPointerDown={beginPointerSession}
        onPointerMove={(event) => {
          const session = pointerSession.current
          if (!session || session.pointerId !== event.pointerId) return
          moveWindow(
            managedWindow.instanceId,
            session.bounds.x + event.clientX - session.startX,
            session.bounds.y + event.clientY - session.startY,
            workspace
          )
        }}
        onPointerUp={finishPointerSession}
        onPointerCancel={finishPointerSession}
      >
        <span className="window-frame__controls">
          <button
            type="button"
            className="window-control window-control--close"
            aria-label={`Close ${app.name}`}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => closeWindow(managedWindow.instanceId)}
          >
            ×
          </button>
          <button
            type="button"
            className="window-control window-control--minimize"
            aria-label={`Minimize ${app.name}`}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => minimizeWindow(managedWindow.instanceId)}
          >
            —
          </button>
          <button
            type="button"
            className="window-control window-control--maximize"
            aria-label={`${managedWindow.mode === 'maximized' ? 'Restore' : 'Maximize'} ${app.name}`}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={toggleMaximize}
          >
            □
          </button>
        </span>
        <span className="window-frame__identity">
          <span className="window-frame__app-icon">{app.icon}</span>
          <span>{managedWindow.title}</span>
        </span>
        {app.manifest.type === 'web' && (
          <span className="window-frame__web-controls">
            <button
              type="button"
              aria-label={`Go back in ${app.name}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() =>
                void window.darwinWebApps?.navigate({
                  instanceId: managedWindow.instanceId,
                  action: 'back'
                })
              }
            >
              ‹
            </button>
            <button
              type="button"
              aria-label={`Go forward in ${app.name}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() =>
                void window.darwinWebApps?.navigate({
                  instanceId: managedWindow.instanceId,
                  action: 'forward'
                })
              }
            >
              ›
            </button>
            <button
              type="button"
              aria-label={`Reload ${app.name}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() =>
                void window.darwinWebApps?.navigate({
                  instanceId: managedWindow.instanceId,
                  action: 'reload'
                })
              }
            >
              ↻
            </button>
          </span>
        )}
      </header>

      <div className="window-frame__content">
        {children ?? (
          <div className="window-placeholder">
            <span>{app.icon}</span>
            <strong>{app.name}</strong>
            <small>{app.description}</small>
          </div>
        )}
      </div>
      {app.manifest.edgeEffect === 'flow' && (
        <div className="window-frame__edge-flow" aria-hidden="true" />
      )}

      {interacting && <div className="window-frame__shield" aria-hidden="true" />}

      {managedWindow.mode === 'normal' &&
        !cinemaMode &&
        resizeDirections.map((direction) => (
          <span
            key={direction}
            className="window-resize-handle"
            data-direction={direction}
            aria-hidden="true"
            onPointerDown={(event) => beginPointerSession(event)}
            onPointerMove={(event) => {
              const session = pointerSession.current
              if (!session || session.pointerId !== event.pointerId) return
              resizeWindow(
                managedWindow.instanceId,
                resizedBounds(
                  session.bounds,
                  direction,
                  event.clientX - session.startX,
                  event.clientY - session.startY
                ),
                workspace
              )
            }}
            onPointerUp={finishPointerSession}
            onPointerCancel={finishPointerSession}
          />
        ))}
    </article>
  )
}

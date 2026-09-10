import { useEffect, useMemo, useRef, useState } from 'react'
import type { ShellApp } from './apps'

export type LauncherStatus = 'ready' | 'loading' | 'error'

interface AppLauncherProps {
  apps: ShellApp[]
  open: boolean
  status?: LauncherStatus
  onClose: () => void
  onLaunchApp: (app: ShellApp) => void
}

export function AppLauncher({
  apps,
  onClose,
  onLaunchApp,
  open,
  status = 'ready'
}: AppLauncherProps) {
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const results = useMemo(
    () =>
      apps.filter((app) => app.name.toLowerCase().includes(query.trim().toLowerCase())),
    [apps, query]
  )

  useEffect(() => {
    if (!open) return
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }, [open])

  if (!open) return null

  const close = () => {
    setQuery('')
    setActiveIndex(0)
    onClose()
  }

  const launch = (app: ShellApp) => {
    onLaunchApp(app)
    close()
  }

  return (
    <div
      className="launcher-layer"
      role="presentation"
      onMouseDown={(event) => event.target === event.currentTarget && close()}
    >
      <section
        className="launcher"
        role="dialog"
        aria-modal="true"
        aria-label="Applications"
      >
        <div className="launcher__search">
          <svg
            aria-hidden="true"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m16 16 4 4" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            aria-label="Search applications"
            placeholder="Search applications"
            onChange={(event) => {
              setQuery(event.target.value)
              setActiveIndex(0)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') close()
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setActiveIndex((index) => Math.min(index + 1, results.length - 1))
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault()
                setActiveIndex((index) => Math.max(index - 1, 0))
              }
              if (event.key === 'Enter' && results[activeIndex])
                launch(results[activeIndex])
            }}
          />
          <kbd>esc</kbd>
        </div>

        <div className="launcher__body" aria-live="polite">
          {status === 'loading' && (
            <p className="launcher__state">Loading applications…</p>
          )}
          {status === 'error' && (
            <p className="launcher__state" role="alert">
              Applications could not be loaded.
            </p>
          )}
          {status === 'ready' && results.length === 0 && (
            <p className="launcher__state">No applications found.</p>
          )}
          {status === 'ready' && results.length > 0 && (
            <div className="launcher__apps" role="listbox" aria-label="Applications">
              {results.map((app, index) => (
                <button
                  key={app.id}
                  type="button"
                  role="option"
                  aria-selected={index === activeIndex}
                  className="launcher__app"
                  data-active={index === activeIndex}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => launch(app)}
                >
                  <span className="launcher__icon">{app.icon}</span>
                  <span>
                    <strong>{app.name}</strong>
                    <small>{app.description}</small>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

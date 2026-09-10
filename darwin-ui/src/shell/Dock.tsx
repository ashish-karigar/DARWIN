import type { ShellApp } from './apps'

interface DockProps {
  apps: ShellApp[]
  activeAppId: string | null
  runningAppIds: string[]
  onLaunchApp: (app: ShellApp) => void
  onOpenLauncher: () => void
}

export function Dock({
  activeAppId,
  apps,
  onLaunchApp,
  onOpenLauncher,
  runningAppIds
}: DockProps) {
  return (
    <nav className="dock" aria-label="Dock">
      <button
        type="button"
        className="dock__launcher"
        aria-label="Open app launcher"
        onClick={onOpenLauncher}
      >
        <span />
        <span />
        <span />
        <span />
      </button>
      <span className="dock__divider" aria-hidden="true" />
      {apps
        .filter((app) => app.pinned)
        .map((app) => (
          <button
            key={app.id}
            type="button"
            className="dock__app"
            data-active={activeAppId === app.id}
            data-running={runningAppIds.includes(app.id)}
            aria-label={`Open ${app.name}`}
            onClick={() => onLaunchApp(app)}
          >
            {app.icon}
            <span className="dock__indicator" aria-hidden="true" />
          </button>
        ))}
    </nav>
  )
}

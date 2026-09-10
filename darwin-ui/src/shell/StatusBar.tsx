import { useEffect, useState } from 'react'
import { IconButton, Tooltip } from '../components/ui'

interface StatusBarProps {
  theme: 'dark' | 'projector'
  onToggleTheme: () => void
}

const formatTime = (date: Date) =>
  new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(date)

export function StatusBar({ onToggleTheme, theme }: StatusBarProps) {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <header className="status-bar">
      <span className="status-bar__wordmark">DARWIN</span>
      <div className="status-bar__system">
        <span className="status-bar__assistant">
          <span className="status-dot" />
          Assistant offline
        </span>
        <time dateTime={now.toISOString()}>{formatTime(now)}</time>
        <Tooltip
          content={`Use ${theme === 'dark' ? 'projector black' : 'dark'} theme`}
          side="bottom"
        >
          <IconButton
            aria-label={`Use ${theme === 'dark' ? 'projector black' : 'dark'} theme`}
            size="small"
            onClick={onToggleTheme}
          >
            <span aria-hidden="true">{theme === 'dark' ? '◐' : '◑'}</span>
          </IconButton>
        </Tooltip>
      </div>
    </header>
  )
}

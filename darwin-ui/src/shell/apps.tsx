import type { ReactNode } from 'react'
import type { AppManifest } from '../../shared/contracts'
import { appRegistry } from '../apps/registry'

export interface ShellApp {
  id: string
  name: string
  description: string
  icon: ReactNode
  pinned: boolean
  instancePolicy: 'single' | 'multiple'
  displayMode: 'window' | 'fullscreen'
  manifest: AppManifest
}

const iconProps = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5
}

const icons: Record<string, ReactNode> = {
  assistant: (
    <svg aria-hidden="true" {...iconProps}>
      <path d="M5 7.5A3.5 3.5 0 0 1 8.5 4h7A3.5 3.5 0 0 1 19 7.5v5a3.5 3.5 0 0 1-3.5 3.5H11l-4.5 3v-3.35A3.5 3.5 0 0 1 5 12.5Z" />
      <path d="M9 9.75h6M9 12.75h4" />
    </svg>
  ),
  settings: (
    <svg aria-hidden="true" {...iconProps}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19 12a7 7 0 0 0-.08-1l2-1.55-2-3.45-2.45 1A7 7 0 0 0 14.75 6L14.4 3h-4.8l-.35 3A7 7 0 0 0 7.53 7L5.08 6l-2 3.45 2 1.55a7 7 0 0 0 0 2l-2 1.55 2 3.45 2.45-1a7 7 0 0 0 1.72 1l.35 3h4.8l.35-3a7 7 0 0 0 1.72-1l2.45 1 2-3.45-2-1.55A7 7 0 0 0 19 12Z" />
    </svg>
  ),
  reminders: (
    <svg aria-hidden="true" {...iconProps}>
      <path d="m5 7 1.5 1.5L9 5.5M11 7h8M5 12l1.5 1.5L9 10.5M11 12h8M5 17l1.5 1.5L9 15.5M11 17h8" />
    </svg>
  ),
  camera: (
    <svg aria-hidden="true" {...iconProps}>
      <rect x="3" y="6.5" width="18" height="13" rx="2.5" />
      <circle cx="12" cy="13" r="3.5" />
      <path d="M8 6.5 9.5 4.5h5L16 6.5" />
    </svg>
  ),
  youtube: (
    <svg aria-hidden="true" {...iconProps}>
      <rect x="3" y="6" width="18" height="12" rx="3" />
      <path d="m10 9 5 3-5 3Z" />
    </svg>
  )
}

const fallbackIcon = (
  <svg aria-hidden="true" {...iconProps}>
    <rect x="4" y="4" width="16" height="16" rx="3" />
  </svg>
)

export const shellApps: ShellApp[] = appRegistry.list().map((manifest) => ({
  id: manifest.id,
  name: manifest.name,
  description: manifest.description,
  icon: manifest.icon ? (icons[manifest.icon] ?? fallbackIcon) : fallbackIcon,
  pinned: manifest.pinned,
  instancePolicy: manifest.instancePolicy,
  displayMode: manifest.displayMode,
  manifest
}))

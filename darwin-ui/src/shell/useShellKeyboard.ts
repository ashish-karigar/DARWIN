import { useEffect } from 'react'
import type { ManagedWindow } from '../stores/windowStore'
import { useWindowStore } from '../stores/windowStore'

interface ShellKeyboardOptions {
  launcherOpen: boolean
  onCloseLauncher: () => void
  onOpenAssistant: () => void
  onToggleLauncher: () => void
}

const isEditableTarget = (target: EventTarget | null): boolean => {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT'
  )
}

const orderedWindows = (windows: ManagedWindow[]) =>
  [...windows].sort((left, right) => right.zIndex - left.zIndex)

export function useShellKeyboard({
  launcherOpen,
  onCloseLauncher,
  onOpenAssistant,
  onToggleLauncher
}: ShellKeyboardOptions) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat || isEditableTarget(event.target)) return

      const commandKey = event.metaKey || event.ctrlKey

      if (commandKey && !event.shiftKey && event.code === 'KeyK') {
        event.preventDefault()
        onToggleLauncher()
        return
      }

      if (commandKey && event.shiftKey && event.code === 'KeyA') {
        event.preventDefault()
        onOpenAssistant()
        return
      }

      if (event.ctrlKey && event.code === 'Tab') {
        event.preventDefault()
        const state = useWindowStore.getState()
        const windows = orderedWindows(state.windows)
        if (windows.length === 0) return

        const currentIndex = windows.findIndex(
          (managedWindow) => managedWindow.instanceId === state.focusedWindowId
        )
        const direction = event.shiftKey ? -1 : 1
        const startingIndex = currentIndex < 0 ? (direction > 0 ? -1 : 0) : currentIndex
        const nextIndex = (startingIndex + direction + windows.length) % windows.length
        const next = windows[nextIndex]
        if (!next) return

        if (next.mode === 'minimized') state.restoreWindow(next.instanceId)
        else state.focusWindow(next.instanceId)
        return
      }

      if (event.key === 'Escape') {
        if (launcherOpen) {
          event.preventDefault()
          onCloseLauncher()
          return
        }

        const state = useWindowStore.getState()
        const focused = state.windows.find(
          (managedWindow) => managedWindow.instanceId === state.focusedWindowId
        )
        if (focused?.mode === 'maximized') {
          event.preventDefault()
          state.restoreWindow(focused.instanceId)
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [launcherOpen, onCloseLauncher, onOpenAssistant, onToggleLauncher])
}

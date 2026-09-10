import { create, type StoreApi, type UseBoundStore } from 'zustand'
import type { WindowBounds, WindowState } from '../../shared/contracts'

export const MIN_WINDOW_WIDTH = 320
export const MIN_WINDOW_HEIGHT = 200
export const TITLE_BAR_HEIGHT = 36
export const MIN_VISIBLE_TITLE_WIDTH = 96

export interface ManagedWindow extends WindowState {
  appId: string
  title: string
}

export interface OpenWindowOptions {
  appId: string
  title: string
  bounds: WindowBounds
  instancePolicy?: 'single' | 'multiple'
}

export interface WindowStoreState {
  windows: ManagedWindow[]
  focusedWindowId: string | null
  nextZIndex: number
  openWindow: (options: OpenWindowOptions) => string
  focusWindow: (instanceId: string) => void
  moveWindow: (instanceId: string, x: number, y: number, workspace: WindowBounds) => void
  resizeWindow: (
    instanceId: string,
    bounds: WindowBounds,
    workspace: WindowBounds
  ) => void
  resizeCinemaWindow: (
    instanceId: string,
    bounds: WindowBounds,
    workspace: WindowBounds
  ) => void
  minimizeWindow: (instanceId: string) => void
  maximizeWindow: (instanceId: string, workspace: WindowBounds) => void
  restoreWindow: (instanceId: string) => void
  closeWindow: (instanceId: string) => void
  reset: () => void
}

type IdFactory = () => string

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(Math.max(value, minimum), maximum)

export const constrainWindowBounds = (
  bounds: WindowBounds,
  workspace: WindowBounds
): WindowBounds => {
  const width = Math.max(MIN_WINDOW_WIDTH, Math.min(bounds.width, workspace.width))
  const height = Math.max(MIN_WINDOW_HEIGHT, Math.min(bounds.height, workspace.height))
  const minimumX = workspace.x - width + Math.min(MIN_VISIBLE_TITLE_WIDTH, width)
  const maximumX =
    workspace.x + workspace.width - Math.min(MIN_VISIBLE_TITLE_WIDTH, width)
  const maximumY = workspace.y + workspace.height - Math.min(TITLE_BAR_HEIGHT, height)

  return {
    x: clamp(bounds.x, minimumX, maximumX),
    y: clamp(bounds.y, workspace.y, maximumY),
    width,
    height
  }
}

const focus = (windows: ManagedWindow[], instanceId: string, zIndex: number) =>
  windows.map((window) => ({
    ...window,
    focused: window.instanceId === instanceId,
    zIndex: window.instanceId === instanceId ? zIndex : window.zIndex
  }))

const topVisibleWindow = (windows: ManagedWindow[]) =>
  windows
    .filter((window) => window.mode !== 'minimized')
    .sort((left, right) => right.zIndex - left.zIndex)[0]

export const createWindowStore = (
  idFactory: IdFactory = () => crypto.randomUUID()
): UseBoundStore<StoreApi<WindowStoreState>> =>
  create<WindowStoreState>((set, get) => ({
    windows: [],
    focusedWindowId: null,
    nextZIndex: 1,

    openWindow: ({ appId, bounds, instancePolicy = 'single', title }) => {
      const state = get()
      const existing =
        instancePolicy === 'single'
          ? state.windows.find((window) => window.appId === appId)
          : undefined

      if (existing) {
        if (existing.mode === 'minimized') state.restoreWindow(existing.instanceId)
        state.focusWindow(existing.instanceId)
        return existing.instanceId
      }

      const instanceId = idFactory()
      const nextWindow: ManagedWindow = {
        appId,
        bounds,
        focused: true,
        instanceId,
        mode: 'normal',
        restoreBounds: null,
        title,
        zIndex: state.nextZIndex
      }

      set({
        windows: [
          ...state.windows.map((window) => ({ ...window, focused: false })),
          nextWindow
        ],
        focusedWindowId: instanceId,
        nextZIndex: state.nextZIndex + 1
      })
      return instanceId
    },

    focusWindow: (instanceId) => {
      const state = get()
      const target = state.windows.find((window) => window.instanceId === instanceId)
      if (!target || target.mode === 'minimized' || state.focusedWindowId === instanceId)
        return
      set({
        windows: focus(state.windows, instanceId, state.nextZIndex),
        focusedWindowId: instanceId,
        nextZIndex: state.nextZIndex + 1
      })
    },

    moveWindow: (instanceId, x, y, workspace) => {
      set((state) => ({
        windows: state.windows.map((window) =>
          window.instanceId === instanceId && window.mode === 'normal'
            ? {
                ...window,
                bounds: constrainWindowBounds({ ...window.bounds, x, y }, workspace)
              }
            : window
        )
      }))
    },

    resizeWindow: (instanceId, bounds, workspace) => {
      set((state) => ({
        windows: state.windows.map((window) =>
          window.instanceId === instanceId && window.mode === 'normal'
            ? { ...window, bounds: constrainWindowBounds(bounds, workspace) }
            : window
        )
      }))
    },

    resizeCinemaWindow: (instanceId, bounds, workspace) => {
      set((state) => ({
        windows: state.windows.map((window) =>
          window.instanceId === instanceId && window.mode !== 'minimized'
            ? {
                ...window,
                bounds: constrainWindowBounds(bounds, workspace),
                mode: 'normal' as const,
                restoreBounds: null
              }
            : window
        )
      }))
    },

    minimizeWindow: (instanceId) => {
      const state = get()
      const target = state.windows.find((window) => window.instanceId === instanceId)
      if (!target || target.mode === 'minimized') return
      const minimized = state.windows.map((window) =>
        window.instanceId === instanceId
          ? { ...window, focused: false, mode: 'minimized' as const }
          : window
      )
      const next = target.focused ? topVisibleWindow(minimized) : undefined
      set({
        windows: next ? focus(minimized, next.instanceId, state.nextZIndex) : minimized,
        focusedWindowId: target.focused
          ? (next?.instanceId ?? null)
          : state.focusedWindowId,
        nextZIndex: next ? state.nextZIndex + 1 : state.nextZIndex
      })
    },

    maximizeWindow: (instanceId, workspace) => {
      const state = get()
      const target = state.windows.find((window) => window.instanceId === instanceId)
      if (!target) return
      set({
        windows: focus(
          state.windows.map((window) =>
            window.instanceId === instanceId
              ? {
                  ...window,
                  bounds: { ...workspace },
                  mode: 'maximized' as const,
                  restoreBounds:
                    window.mode === 'normal' ? { ...window.bounds } : window.restoreBounds
                }
              : window
          ),
          instanceId,
          state.nextZIndex
        ),
        focusedWindowId: instanceId,
        nextZIndex: state.nextZIndex + 1
      })
    },

    restoreWindow: (instanceId) => {
      const state = get()
      const target = state.windows.find((window) => window.instanceId === instanceId)
      if (!target) return
      set({
        windows: focus(
          state.windows.map((window) =>
            window.instanceId === instanceId
              ? {
                  ...window,
                  bounds: window.restoreBounds ?? window.bounds,
                  mode: 'normal' as const,
                  restoreBounds: null
                }
              : window
          ),
          instanceId,
          state.nextZIndex
        ),
        focusedWindowId: instanceId,
        nextZIndex: state.nextZIndex + 1
      })
    },

    closeWindow: (instanceId) => {
      const state = get()
      const remaining = state.windows.filter((window) => window.instanceId !== instanceId)
      const shouldRefocus = state.focusedWindowId === instanceId
      const next = shouldRefocus ? topVisibleWindow(remaining) : undefined
      set({
        windows: next ? focus(remaining, next.instanceId, state.nextZIndex) : remaining,
        focusedWindowId: shouldRefocus
          ? (next?.instanceId ?? null)
          : state.focusedWindowId,
        nextZIndex: next ? state.nextZIndex + 1 : state.nextZIndex
      })
    },

    reset: () => set({ windows: [], focusedWindowId: null, nextZIndex: 1 })
  }))

export const useWindowStore = createWindowStore()

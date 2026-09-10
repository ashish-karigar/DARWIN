import { beforeEach, describe, expect, it } from 'vitest'
import {
  MIN_VISIBLE_TITLE_WIDTH,
  TITLE_BAR_HEIGHT,
  constrainWindowBounds,
  createWindowStore
} from './windowStore'

const workspace = { x: 0, y: 44, width: 1280, height: 676 }
const bounds = { x: 120, y: 100, width: 720, height: 480 }
let nextId = 0
const store = createWindowStore(
  () => `00000000-0000-4000-8000-${String(++nextId).padStart(12, '0')}`
)

const open = (
  appId = 'darwin.settings',
  instancePolicy: 'single' | 'multiple' = 'single'
) => store.getState().openWindow({ appId, title: appId, bounds, instancePolicy })

describe('window store', () => {
  beforeEach(() => {
    nextId = 0
    store.getState().reset()
  })

  it('opens a focused window with a stable instance ID', () => {
    const id = open()
    const state = store.getState()
    expect(state.focusedWindowId).toBe(id)
    expect(state.windows).toEqual([
      expect.objectContaining({ instanceId: id, focused: true, zIndex: 1 })
    ])
  })

  it('focuses an existing single-instance app instead of duplicating it', () => {
    const original = open()
    open('darwin.assistant')
    const reopened = open()
    expect(reopened).toBe(original)
    expect(store.getState().windows).toHaveLength(2)
    expect(store.getState().focusedWindowId).toBe(original)
  })

  it('permits multiple instances when requested', () => {
    expect(open('darwin.notes', 'multiple')).not.toBe(open('darwin.notes', 'multiple'))
    expect(store.getState().windows).toHaveLength(2)
  })

  it('keeps only one window focused and raises its z-order', () => {
    const first = open()
    const second = open('darwin.assistant')
    store.getState().focusWindow(first)
    const state = store.getState()
    expect(state.focusedWindowId).toBe(first)
    expect(
      state.windows.find((window) => window.instanceId === first)?.zIndex
    ).toBeGreaterThan(
      state.windows.find((window) => window.instanceId === second)?.zIndex ?? 0
    )
    expect(state.windows.filter((window) => window.focused)).toHaveLength(1)
  })

  it('minimizes and focuses the highest remaining visible window', () => {
    const first = open()
    const second = open('darwin.assistant')
    store.getState().minimizeWindow(second)
    expect(store.getState().focusedWindowId).toBe(first)
    expect(
      store.getState().windows.find((window) => window.instanceId === second)?.mode
    ).toBe('minimized')
  })

  it('does not disturb focus when minimizing a background window', () => {
    const first = open()
    const second = open('darwin.assistant')
    store.getState().minimizeWindow(first)
    expect(store.getState().focusedWindowId).toBe(second)
  })

  it('maximizes and restores the previous bounds', () => {
    const id = open()
    store.getState().maximizeWindow(id, workspace)
    expect(store.getState().windows[0]).toMatchObject({
      bounds: workspace,
      mode: 'maximized'
    })
    store.getState().restoreWindow(id)
    expect(store.getState().windows[0]).toMatchObject({ bounds, mode: 'normal' })
  })

  it('lets cinema resizing convert a maximized window back to a normal window', () => {
    const id = open('darwin.youtube')
    store.getState().maximizeWindow(id, workspace)
    const resized = { x: 0, y: 44, width: 1100, height: 620 }
    store.getState().resizeCinemaWindow(id, resized, workspace)
    expect(store.getState().windows[0]).toMatchObject({
      bounds: resized,
      mode: 'normal',
      restoreBounds: null
    })
  })

  it('closes a window and refocuses the next visible window', () => {
    const first = open()
    const second = open('darwin.assistant')
    store.getState().closeWindow(second)
    expect(store.getState().windows).toHaveLength(1)
    expect(store.getState().focusedWindowId).toBe(first)
  })

  it('keeps a reachable section of the title bar inside the workspace', () => {
    const constrained = constrainWindowBounds(
      { x: -2000, y: 2000, width: 700, height: 400 },
      workspace
    )
    expect(constrained.x).toBe(-700 + MIN_VISIBLE_TITLE_WIDTH)
    expect(constrained.y).toBe(workspace.y + workspace.height - TITLE_BAR_HEIGHT)
  })

  it('enforces minimum sizes and workspace maximums', () => {
    expect(
      constrainWindowBounds({ x: 0, y: 44, width: 10, height: 10 }, workspace)
    ).toMatchObject({ width: 320, height: 200 })
    expect(
      constrainWindowBounds({ x: 0, y: 44, width: 5000, height: 5000 }, workspace)
    ).toMatchObject({ width: workspace.width, height: workspace.height })
  })
})

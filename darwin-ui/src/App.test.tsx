import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { App } from './App'
import { useSettingsStore } from './stores/settingsStore'
import { useWindowStore } from './stores/windowStore'

describe('DARWIN desktop shell', () => {
  beforeEach(() => {
    useWindowStore.getState().reset()
    useSettingsStore.getState().reset()
    useSettingsStore.setState({ onboardingComplete: true, theme: 'dark' })
    Object.defineProperty(window, 'darwinHost', {
      configurable: true,
      value: {
        versions: { chrome: '1.0.0', electron: '44.3.0', node: '26.7.0' },
        credentials: {
          store: async () => ({ ok: true }),
          has: async () => false,
          remove: async () => ({ ok: true })
        }
      }
    })
  })

  it('renders the status bar, workspace, and dock', () => {
    render(<App />)
    expect(screen.getByText('DARWIN')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Desktop workspace' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Dock' })).toBeInTheDocument()
  })

  it('asks for service setup on first startup', () => {
    useSettingsStore.setState({ onboardingComplete: false })
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Set up Darwin' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Set up later' }))
    expect(
      screen.queryByRole('heading', { name: 'Set up Darwin' })
    ).not.toBeInTheDocument()
    expect(useSettingsStore.getState().onboardingComplete).toBe(true)
  })

  it('opens the launcher and selects an application', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Open app launcher' }))
    fireEvent.click(screen.getByRole('option', { name: /Settings/ }))
    expect(screen.getByRole('heading', { name: 'General' })).toBeInTheDocument()
    expect(
      screen.queryByRole('article', { name: 'Settings window' })
    ).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Applications' })).not.toBeInTheDocument()
  })

  it('supports the visible window lifecycle', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Open Assistant' }))
    expect(screen.getByRole('article', { name: 'Assistant window' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Minimize Assistant' }))
    expect(
      screen.queryByRole('article', { name: 'Assistant window' })
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open Assistant' }))
    fireEvent.click(screen.getByRole('button', { name: 'Maximize Assistant' }))
    expect(screen.getByRole('button', { name: 'Restore Assistant' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Close Assistant' }))
    expect(
      screen.queryByRole('article', { name: 'Assistant window' })
    ).not.toBeInTheDocument()
  })

  it('moves a normal window using its title bar', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Open Assistant' }))
    const titlebar = screen
      .getByRole('article', { name: 'Assistant window' })
      .querySelector('.window-frame__titlebar')
    expect(titlebar).not.toBeNull()

    fireEvent.pointerDown(titlebar!, {
      button: 0,
      pointerId: 1,
      clientX: 200,
      clientY: 110
    })
    fireEvent.pointerMove(titlebar!, { pointerId: 1, clientX: 250, clientY: 140 })

    expect(useWindowStore.getState().windows[0]?.bounds).toMatchObject({ x: 170, y: 122 })
  })

  it('opens and closes the launcher with the command shortcut and Escape', () => {
    render(<App />)
    fireEvent.keyDown(window, { code: 'KeyK', metaKey: true })
    expect(screen.getByRole('dialog', { name: 'Applications' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Applications' })).not.toBeInTheDocument()
  })

  it('opens Assistant with its shell shortcut', () => {
    render(<App />)
    fireEvent.keyDown(window, { code: 'KeyA', metaKey: true, shiftKey: true })
    expect(screen.getByRole('article', { name: 'Assistant window' })).toBeInTheDocument()
  })

  it('cycles focus through open windows in both directions', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Open Assistant' }))
    const assistantId = useWindowStore.getState().focusedWindowId
    fireEvent.click(screen.getByRole('button', { name: 'Open YouTube' }))
    const youtubeId = useWindowStore.getState().focusedWindowId

    fireEvent.keyDown(window, { code: 'Tab', ctrlKey: true })
    expect(useWindowStore.getState().focusedWindowId).toBe(assistantId)
    fireEvent.keyDown(window, { code: 'Tab', ctrlKey: true, shiftKey: true })
    expect(useWindowStore.getState().focusedWindowId).toBe(youtubeId)
  })

  it('uses Escape to restore a maximized window without closing it', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Open Assistant' }))
    fireEvent.click(screen.getByRole('button', { name: 'Maximize Assistant' }))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.getByRole('button', { name: 'Maximize Assistant' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Assistant window' })).toBeInTheDocument()
  })

  it('does not capture shell shortcuts from editable fields', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Open app launcher' }))
    const search = screen.getByRole('textbox', { name: 'Search applications' })
    fireEvent.keyDown(search, { code: 'KeyA', metaKey: true, shiftKey: true })
    expect(
      screen.queryByRole('article', { name: 'Assistant window' })
    ).not.toBeInTheDocument()
  })

  it('switches between dark and projector-black themes', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Use projector black theme' }))
    expect(screen.getByRole('button', { name: 'Use dark theme' })).toBeInTheDocument()
  })
})

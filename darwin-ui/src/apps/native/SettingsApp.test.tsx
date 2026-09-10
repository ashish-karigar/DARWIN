import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSettingsStore } from '../../stores/settingsStore'
import { SettingsApp } from './SettingsApp'

const credentialStore = vi.fn(async () => ({ ok: true }))
const credentialHas = vi.fn(async (id: string) => {
  void id
  return false
})
const credentialRemove = vi.fn(async () => ({ ok: true }))

describe('SettingsApp', () => {
  beforeEach(() => {
    credentialStore.mockClear()
    credentialHas.mockClear()
    credentialRemove.mockClear()
    useSettingsStore.getState().reset()
    Object.defineProperty(window, 'darwinHost', {
      configurable: true,
      value: {
        versions: { chrome: '1', electron: '44', node: '26' },
        credentials: {
          store: credentialStore,
          has: credentialHas,
          remove: credentialRemove
        }
      }
    })
  })

  it('stores entered secrets through the secure host bridge', async () => {
    const onClose = vi.fn()
    render(<SettingsApp onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.change(screen.getByLabelText('Groq API key'), {
      target: { value: 'secret-value' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Finish setup' }))
    await waitFor(() =>
      expect(credentialStore).toHaveBeenCalledWith('groq.apiKey', 'secret-value')
    )
    expect(useSettingsStore.getState().serviceState.groq).toBe(true)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('renders full-screen settings sections after onboarding', () => {
    useSettingsStore.setState({ onboardingComplete: true })
    render(<SettingsApp />)
    fireEvent.click(screen.getByRole('button', { name: 'Appearance' }))
    expect(screen.getByRole('heading', { name: 'Appearance' })).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: 'Theme' }), {
      target: { value: 'projector' }
    })
    expect(useSettingsStore.getState().theme).toBe('projector')
  })

  it('allows credentials to be configured from the Services section', async () => {
    useSettingsStore.setState({ onboardingComplete: true })
    credentialHas.mockImplementation(async (id: string) => id === 'groq.apiKey')
    render(<SettingsApp />)
    fireEvent.click(screen.getByRole('button', { name: 'Services' }))
    fireEvent.change(screen.getByLabelText('Fish Audio API key'), {
      target: { value: 'fish-secret' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() =>
      expect(credentialStore).toHaveBeenCalledWith('fishAudio.apiKey', 'fish-secret')
    )
    expect(screen.getByText('Service settings saved.')).toBeInTheDocument()
  })

  it('can remove an existing credential', async () => {
    useSettingsStore.setState({
      onboardingComplete: true,
      serviceState: { groq: true, ollama: false, fishAudio: false, spotify: false }
    })
    credentialHas.mockImplementation(async (id: string) => id === 'groq.apiKey')
    render(<SettingsApp />)
    fireEvent.click(screen.getByRole('button', { name: 'Services' }))
    const disconnect = await screen.findByRole('button', { name: 'Disconnect' })
    fireEvent.click(disconnect)
    await waitFor(() => expect(credentialRemove).toHaveBeenCalledWith('groq.apiKey'))
  })
})

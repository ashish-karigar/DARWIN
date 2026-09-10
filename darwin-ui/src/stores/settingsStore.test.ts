import { beforeEach, describe, expect, it } from 'vitest'
import { defaultPreferences, preferencesSchema, useSettingsStore } from './settingsStore'

describe('settings store', () => {
  beforeEach(() => {
    localStorage.clear()
    useSettingsStore.getState().reset()
  })

  it('updates user preferences', () => {
    const settings = useSettingsStore.getState()
    settings.setTheme('projector')
    settings.setPrimaryInput('gesture')
    settings.setVoiceEnabled(false)
    expect(useSettingsStore.getState()).toMatchObject({
      theme: 'projector',
      primaryInput: 'gesture',
      voiceEnabled: false
    })
  })

  it('persists only non-secret preference state', () => {
    useSettingsStore.getState().completeOnboarding({
      groq: true,
      ollama: true,
      fishAudio: false,
      spotify: false
    })
    const persisted = localStorage.getItem('darwin.preferences') ?? ''
    expect(persisted).toContain('onboardingComplete')
    expect(persisted).not.toContain('apiKey')
    expect(persisted).not.toContain('clientSecret')
  })

  it('returns every preference to its default', () => {
    useSettingsStore.getState().setTheme('projector')
    useSettingsStore.getState().reset()
    expect(useSettingsStore.getState()).toMatchObject(defaultPreferences)
  })

  it('rejects malformed persisted preferences', () => {
    expect(
      preferencesSchema.safeParse({ ...defaultPreferences, theme: 'neon' }).success
    ).toBe(false)
  })
})

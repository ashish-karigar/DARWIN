import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { z } from 'zod'

export type ThemePreference = 'system' | 'dark' | 'projector'
export type InputPreference = 'mouse' | 'gesture'

export interface ServiceState {
  groq: boolean
  ollama: boolean
  fishAudio: boolean
  spotify: boolean
}

export interface DarwinPreferences {
  onboardingComplete: boolean
  theme: ThemePreference
  reducedMotion: boolean
  neuralBrightness: number
  neuralThickness: number
  neuralWarmth: number
  primaryInput: InputPreference
  voiceEnabled: boolean
  rememberWindowPositions: boolean
  serviceState: ServiceState
}

export const preferencesSchema = z.object({
  onboardingComplete: z.boolean(),
  theme: z.enum(['system', 'dark', 'projector']),
  reducedMotion: z.boolean(),
  neuralBrightness: z.number().min(0.5).max(8).default(0.5),
  neuralThickness: z.number().min(0.5).max(5).default(0.5),
  neuralWarmth: z.number().min(0).max(10).default(0.3),
  primaryInput: z.enum(['mouse', 'gesture']),
  voiceEnabled: z.boolean(),
  rememberWindowPositions: z.boolean(),
  serviceState: z.object({
    groq: z.boolean(),
    ollama: z.boolean(),
    fishAudio: z.boolean(),
    spotify: z.boolean()
  })
})

interface SettingsState extends DarwinPreferences {
  completeOnboarding: (serviceState: ServiceState) => void
  setTheme: (theme: ThemePreference) => void
  setReducedMotion: (enabled: boolean) => void
  setNeuralBrightness: (value: number) => void
  setNeuralThickness: (value: number) => void
  setNeuralWarmth: (value: number) => void
  setPrimaryInput: (input: InputPreference) => void
  setVoiceEnabled: (enabled: boolean) => void
  setRememberWindowPositions: (enabled: boolean) => void
  setServiceConfigured: (service: keyof ServiceState, configured: boolean) => void
  reset: () => void
}

export const defaultPreferences: DarwinPreferences = {
  onboardingComplete: false,
  theme: 'dark',
  reducedMotion: false,
  neuralBrightness: 0.5,
  neuralThickness: 0.5,
  neuralWarmth: 0.3,
  primaryInput: 'mouse',
  voiceEnabled: true,
  rememberWindowPositions: true,
  serviceState: { groq: false, ollama: false, fishAudio: false, spotify: false }
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      ...defaultPreferences,
      completeOnboarding: (serviceState) =>
        set({ onboardingComplete: true, serviceState }),
      setTheme: (theme) => set({ theme }),
      setReducedMotion: (reducedMotion) => set({ reducedMotion }),
      setNeuralBrightness: (neuralBrightness) => set({ neuralBrightness }),
      setNeuralThickness: (neuralThickness) => set({ neuralThickness }),
      setNeuralWarmth: (neuralWarmth) => set({ neuralWarmth }),
      setPrimaryInput: (primaryInput) => set({ primaryInput }),
      setVoiceEnabled: (voiceEnabled) => set({ voiceEnabled }),
      setRememberWindowPositions: (rememberWindowPositions) =>
        set({ rememberWindowPositions }),
      setServiceConfigured: (service, configured) =>
        set((state) => ({
          serviceState: { ...state.serviceState, [service]: configured }
        })),
      reset: () => set(defaultPreferences)
    }),
    {
      name: 'darwin.preferences',
      version: 1,
      partialize: (state) => ({
        onboardingComplete: state.onboardingComplete,
        theme: state.theme,
        reducedMotion: state.reducedMotion,
        neuralBrightness: state.neuralBrightness,
        neuralThickness: state.neuralThickness,
        neuralWarmth: state.neuralWarmth,
        primaryInput: state.primaryInput,
        voiceEnabled: state.voiceEnabled,
        rememberWindowPositions: state.rememberWindowPositions,
        serviceState: state.serviceState
      }),
      merge: (persistedState, currentState) => {
        const result = preferencesSchema.safeParse(persistedState)
        return result.success ? { ...currentState, ...result.data } : currentState
      }
    }
  )
)

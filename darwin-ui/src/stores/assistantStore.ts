import { create } from 'zustand'
import { z } from 'zod'

export const assistantStateSchema = z.enum([
  'idle',
  'listening',
  'transcribing',
  'thinking',
  'speaking',
  'error'
])
export type AssistantState = z.infer<typeof assistantStateSchema>

const stateEventSchema = z.union([
  z.object({
    state: assistantStateSchema,
    connected: z.boolean(),
    source: z.string().length(12)
  }),
  z.object({ audioLevel: z.number().min(0).max(1), source: z.string().length(12) }),
  z.object({
    activity: z.object({
      requestId: z.string().uuid(),
      skill: z.string().min(1).max(80),
      phase: z.enum(['started', 'completed', 'failed'])
    }),
    source: z.string().length(12)
  })
])

interface AssistantStore {
  state: AssistantState
  connected: boolean
  audioLevel: number
  connect: () => () => void
}

export const useAssistantStore = create<AssistantStore>((set) => ({
  state: 'idle',
  connected: false,
  audioLevel: 0,
  connect: () => {
    const bridge = window.darwinAssistant
    if (!bridge) return () => undefined
    void bridge.getState().then((value) => {
      const event = z
        .object({
          state: assistantStateSchema,
          connected: z.boolean(),
          audioLevel: z.number().min(0).max(1)
        })
        .safeParse(value)
      if (event.success) set(event.data)
    })
    const subscriptionId = bridge.subscribeState((value) => {
      const event = stateEventSchema.safeParse(value)
      if (!event.success) return
      if ('activity' in event.data) {
        if (event.data.activity.phase === 'started') {
          const zone =
            [...event.data.activity.skill].reduce(
              (total, character) => total + character.charCodeAt(0),
              0
            ) % 6
          window.dispatchEvent(new CustomEvent('darwin:activity', { detail: { zone } }))
        }
      } else if ('audioLevel' in event.data) set({ audioLevel: event.data.audioLevel })
      else
        set({
          state: event.data.state,
          connected: event.data.connected,
          ...(event.data.state === 'listening' ? {} : { audioLevel: 0 })
        })
    })
    return () => bridge.unsubscribeState(subscriptionId)
  }
}))

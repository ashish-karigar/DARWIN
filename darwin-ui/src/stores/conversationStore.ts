import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { z } from 'zod'
import { parseServerMessage } from '../../shared/contracts'

export type ConversationEntry = {
  id: string
  requestId: string
  role: 'human' | 'darwin'
  content: string
  status: 'pending' | 'complete' | 'error'
  createdAt: string
}

type PendingConfirmation = {
  requestId: string
  summary: string
  risk: 'low' | 'reversible_write' | 'destructive' | 'sensitive'
  expiresAt: string
}

type RuntimeStatus = 'starting' | 'connected' | 'reconnecting' | 'error' | 'stopped'

interface ConversationStore {
  messages: ConversationEntry[]
  runtimeStatus: RuntimeStatus
  launchSessionId: string | null
  activeRequestId: string | null
  assistantState: string
  pendingConfirmation: PendingConfirmation | null
  connect: () => () => void
  submit: (content: string) => Promise<boolean>
  listen: () => Promise<boolean>
  cancel: (requestId: string) => Promise<void>
  resolveConfirmation: (approved: boolean) => Promise<void>
  clear: () => void
}

const statusSchema = z.object({
  status: z.enum(['starting', 'connected', 'reconnecting', 'error', 'stopped']),
  connected: z.boolean(),
  sessionId: z.string().min(1)
})

const capped = (messages: ConversationEntry[]) => messages.slice(-100)

export const useConversationStore = create<ConversationStore>()(
  persist(
    (set, get) => ({
      messages: [],
      runtimeStatus: 'starting',
      launchSessionId: null,
      activeRequestId: null,
      assistantState: 'idle',
      pendingConfirmation: null,
      connect: () => {
        const bridge = window.darwinAssistantSession
        if (!bridge) {
          set({ runtimeStatus: 'error' })
          return () => undefined
        }
        const applyStatus = (value: unknown) => {
          const status = statusSchema.safeParse(value)
          if (!status.success) return
          set((state) => {
            const newLaunch = state.launchSessionId !== status.data.sessionId
            return {
              runtimeStatus: status.data.status,
              launchSessionId: status.data.sessionId,
              activeRequestId:
                status.data.status === 'connected' ? state.activeRequestId : null,
              messages: newLaunch
                ? []
                : status.data.status === 'error' || status.data.status === 'stopped'
                  ? state.messages.map((message) =>
                      message.status === 'pending'
                        ? { ...message, status: 'error' as const }
                        : message
                    )
                  : state.messages
            }
          })
        }
        void bridge.getStatus().then(applyStatus)
        const statusSubscription = bridge.subscribeStatus((value) => {
          applyStatus(value)
        })
        const eventSubscription = bridge.subscribeEvents((value) => {
          try {
            const event = parseServerMessage(value)
            if (event.type === 'assistant.state') {
              set((state) => ({
                assistantState: event.state,
                activeRequestId:
                  event.state === 'idle' || event.state === 'error'
                    ? !event.requestId || event.requestId === state.activeRequestId
                      ? null
                      : state.activeRequestId
                    : event.requestId ?? state.activeRequestId
              }))
            } else if (event.type === 'assistant.transcription') {
              set((state) => ({
                messages: capped((state.messages.some((message) =>
                    message.requestId === event.requestId && message.role === 'human'
                  ) ? state.messages.map((message) =>
                    message.requestId === event.requestId && message.role === 'human'
                      ? {
                          ...message,
                          content: event.content,
                          status: 'pending' as const
                        }
                      : message
                  ) : [...state.messages, {
                    id: event.messageId,
                    requestId: event.requestId,
                    role: 'human' as const,
                    content: event.content,
                    status: 'pending' as const,
                    createdAt: event.timestamp
                  }]))
              }))
            } else if (event.type === 'assistant.response') {
              set((state) => {
                const existing = state.messages.find(
                  (message) =>
                    message.role === 'darwin' && message.requestId === event.requestId
                )
                const messages = state.messages.map((message) =>
                  message.role === 'human' && message.requestId === event.requestId
                    ? { ...message, status: 'complete' as const }
                    : message
                )
                if (existing) {
                  return {
                    messages: capped(
                      messages.map((message) =>
                        message.id === existing.id
                          ? {
                              ...message,
                              content: event.content,
                              status: event.final ? 'complete' : 'pending'
                            }
                          : message
                      )
                    ),
                    pendingConfirmation: null
                  }
                }
                return {
                  messages: capped([
                    ...messages,
                    {
                      id: event.messageId,
                      requestId: event.requestId,
                      role: 'darwin',
                      content: event.content,
                      status: event.final ? 'complete' : 'pending',
                      createdAt: event.timestamp
                    }
                  ]),
                  pendingConfirmation: null
                }
              })
            } else if (event.type === 'confirmation.required') {
              set({
                pendingConfirmation: {
                  requestId: event.requestId,
                  summary: event.summary,
                  risk: event.risk,
                  expiresAt: event.expiresAt
                }
              })
            } else if (event.type === 'error' && event.requestId) {
              if (event.code === 'superseded' || event.code === 'cancelled') {
                set((state) => ({
                  messages: state.messages
                    .filter(
                      (message) =>
                        !(
                          message.requestId === event.requestId &&
                          message.role === 'darwin'
                        )
                    )
                    .map((message) =>
                      message.requestId === event.requestId
                        ? { ...message, status: 'complete' as const }
                        : message
                    ),
                  assistantState: 'idle',
                  activeRequestId:
                    state.activeRequestId === event.requestId
                      ? null
                      : state.activeRequestId,
                  pendingConfirmation: null
                }))
                return
              }
              set((state) => ({
                messages: state.messages.map((message) =>
                  message.requestId === event.requestId
                    ? { ...message, status: 'error' as const }
                    : message
                ),
                assistantState: 'error',
                activeRequestId:
                  state.activeRequestId === event.requestId
                    ? null
                    : state.activeRequestId,
                pendingConfirmation: null
              }))
            }
          } catch {
            // Electron already validates messages; renderer validation is defense in depth.
          }
        })
        return () => {
          bridge.unsubscribe(statusSubscription)
          bridge.unsubscribe(eventSubscription)
        }
      },
      submit: async (content) => {
        const bridge = window.darwinAssistantSession
        const normalized = content.trim()
        if (!bridge || !normalized || get().runtimeStatus !== 'connected') return false
        const requestId = crypto.randomUUID()
        set((state) => ({
          activeRequestId: requestId,
          messages: capped([
            ...state.messages,
            {
              id: requestId,
              requestId,
              role: 'human',
              content: normalized,
              status: 'pending',
              createdAt: new Date().toISOString()
            }
          ])
        }))
        const result = await bridge.submit(requestId, normalized)
        if (!result.ok) {
          set((state) => ({
            activeRequestId:
              state.activeRequestId === requestId ? null : state.activeRequestId,
            messages: state.messages.map((message) =>
              message.requestId === requestId
                ? { ...message, status: 'error' as const }
                : message
            )
          }))
        }
        return result.ok
      },
      listen: async () => {
        const bridge = window.darwinAssistantSession
        if (!bridge || get().runtimeStatus !== 'connected') return false
        const requestId = crypto.randomUUID()
        set((state) => ({
          activeRequestId: requestId,
          messages: capped([
            ...state.messages,
            {
              id: requestId,
              requestId,
              role: 'human',
              content: 'Listening…',
              status: 'pending',
              createdAt: new Date().toISOString()
            }
          ])
        }))
        const result = await bridge.listen(requestId)
        if (!result.ok) {
          set((state) => ({
            activeRequestId:
              state.activeRequestId === requestId ? null : state.activeRequestId,
            messages: state.messages.map((message) =>
              message.requestId === requestId
                ? { ...message, status: 'error' as const }
                : message
            )
          }))
        }
        return result.ok
      },
      cancel: async (requestId) => {
        const result = await window.darwinAssistantSession?.cancel(requestId)
        if (result?.ok) {
          set((state) => ({
            messages: state.messages
              .filter(
                (message) =>
                  !(message.requestId === requestId && message.role === 'darwin')
              )
              .map((message) =>
                message.requestId === requestId
                  ? { ...message, status: 'complete' as const }
                  : message
              ),
            assistantState: 'idle',
            activeRequestId:
              state.activeRequestId === requestId ? null : state.activeRequestId,
            pendingConfirmation: null
          }))
        }
      },
      resolveConfirmation: async (approved) => {
        const confirmation = get().pendingConfirmation
        if (!confirmation) return
        set({ pendingConfirmation: null })
        await window.darwinAssistantSession?.confirm(confirmation.requestId, approved)
      },
      clear: () => set({ messages: [], pendingConfirmation: null })
    }),
    {
      name: 'darwin-conversation',
      partialize: (state) => ({
        messages: state.messages,
        launchSessionId: state.launchSessionId
      })
    }
  )
)

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PROTOCOL_VERSION } from '../../shared/contracts'
import { useConversationStore } from './conversationStore'

const base = (type: string) => ({
  protocolVersion: PROTOCOL_VERSION,
  messageId: crypto.randomUUID(),
  timestamp: new Date().toISOString(),
  type
})

describe('conversation store', () => {
  let eventListener: (value: unknown) => void
  let statusListener: (value: unknown) => void
  const submit = vi.fn(async (requestId: string) => ({ ok: true, requestId }))
  const confirm = vi.fn(async () => ({ ok: true }))
  const cancel = vi.fn(async () => ({ ok: true }))

  beforeEach(() => {
    localStorage.clear()
    submit.mockClear()
    confirm.mockClear()
    cancel.mockClear()
    useConversationStore.setState({
      messages: [],
      runtimeStatus: 'starting',
      launchSessionId: null,
      activeRequestId: null,
      assistantState: 'idle',
      pendingConfirmation: null
    })
    Object.defineProperty(window, 'darwinAssistantSession', {
      configurable: true,
      value: {
        getStatus: async () => ({
          status: 'connected',
          connected: true,
          sessionId: 'desktop-test'
        }),
        submit,
        listen: async (requestId: string) => ({ ok: true, requestId }),
        cancel,
        confirm,
        subscribeEvents: (listener: (value: unknown) => void) => {
          eventListener = listener
          return 'events'
        },
        subscribeStatus: (listener: (value: unknown) => void) => {
          statusListener = listener
          return 'status'
        },
        unsubscribe: vi.fn()
      }
    })
  })

  it('correlates a user message with the final DARWIN response', async () => {
    const disconnect = useConversationStore.getState().connect()
    statusListener({
      status: 'connected',
      connected: true,
      sessionId: 'desktop-test'
    })

    expect(await useConversationStore.getState().submit('Status report')).toBe(true)
    const requestId = useConversationStore.getState().messages[0]!.requestId
    eventListener({
      ...base('assistant.response'),
      requestId,
      content: 'All systems nominal.',
      final: true
    })

    expect(useConversationStore.getState().messages).toMatchObject([
      { role: 'human', content: 'Status report', status: 'complete' },
      { role: 'darwin', content: 'All systems nominal.', status: 'complete' }
    ])
    disconnect()
  })

  it('removes a stale partial response when its turn is superseded', async () => {
    const disconnect = useConversationStore.getState().connect()
    statusListener({
      status: 'connected',
      connected: true,
      sessionId: 'desktop-test'
    })
    await useConversationStore.getState().submit("What's the weather today?")
    const requestId = useConversationStore.getState().messages[0]!.requestId

    eventListener({
      ...base('assistant.response'),
      type: 'assistant.response',
      requestId,
      content: 'Checking Middletown now.',
      final: false
    })
    eventListener({
      ...base('error'),
      type: 'error',
      requestId,
      code: 'superseded',
      message: 'Request cancelled.',
      recoverable: true
    })

    expect(useConversationStore.getState().messages).toEqual([
      expect.objectContaining({ role: 'human', status: 'complete', requestId })
    ])
    expect(useConversationStore.getState().assistantState).not.toBe('error')
    disconnect()
  })

  it('surfaces and resolves structured confirmations', async () => {
    useConversationStore.getState().connect()
    const requestId = crypto.randomUUID()
    eventListener({
      ...base('confirmation.required'),
      requestId,
      summary: 'Create a reminder',
      risk: 'reversible_write',
      expiresAt: new Date(Date.now() + 30_000).toISOString()
    })

    expect(useConversationStore.getState().pendingConfirmation?.summary).toBe(
      'Create a reminder'
    )
    await useConversationStore.getState().resolveConfirmation(true)
    expect(confirm).toHaveBeenCalledWith(requestId, true)
    expect(useConversationStore.getState().pendingConfirmation).toBeNull()
  })

  it('stops an active turn immediately in the visible conversation', async () => {
    useConversationStore.getState().connect()
    statusListener({
      status: 'connected',
      connected: true,
      sessionId: 'desktop-test'
    })
    await useConversationStore.getState().submit('Keep working')
    const requestId = useConversationStore.getState().activeRequestId!

    await useConversationStore.getState().cancel(requestId)

    expect(cancel).toHaveBeenCalledWith(requestId)
    expect(useConversationStore.getState().activeRequestId).toBeNull()
    expect(useConversationStore.getState().messages[0]).toMatchObject({
      content: 'Keep working',
      status: 'complete'
    })
  })

  it('clears visible history when Electron starts a new launch session', () => {
    useConversationStore.setState({
      launchSessionId: 'desktop-old',
      messages: [
        {
          id: 'old-message',
          requestId: 'old-request',
          role: 'human',
          content: 'Previous launch',
          status: 'complete',
          createdAt: new Date().toISOString()
        }
      ]
    })
    useConversationStore.getState().connect()
    statusListener({
      status: 'connected',
      connected: true,
      sessionId: 'desktop-new'
    })

    expect(useConversationStore.getState().messages).toEqual([])
    expect(useConversationStore.getState().launchSessionId).toBe('desktop-new')
  })
})

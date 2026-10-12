/// <reference types="vite/client" />

interface Window {
  readonly darwinHost?: {
    readonly versions: {
      readonly chrome: string
      readonly electron: string
      readonly node: string
    }
    readonly credentials: {
      store: (
        credentialId: string,
        secret: string
      ) => Promise<{
        ok: boolean
        error?: 'invalid_id' | 'secure_storage_unavailable' | 'storage_error'
      }>
      has: (credentialId: string) => Promise<boolean>
      remove: (credentialId: string) => Promise<{
        ok: boolean
        error?: 'invalid_id' | 'secure_storage_unavailable' | 'storage_error'
      }>
    }
  }
  readonly darwinWebApps?: {
    create: (request: unknown) => Promise<{ ok: boolean }>
    update: (request: unknown) => Promise<{ ok: boolean }>
    destroy: (instanceId: string) => Promise<{ ok: boolean }>
    navigate: (request: unknown) => Promise<{ ok: boolean }>
    controlMedia: (
      action: 'pause' | 'resume' | 'next' | 'previous'
    ) => Promise<{ ok: boolean }>
    subscribeStatus: (listener: (event: unknown) => void) => string
    unsubscribeStatus: (subscriptionId: string) => void
    subscribeMedia: (listener: (event: unknown) => void) => string
    unsubscribeMedia: (subscriptionId: string) => void
  }
  readonly darwinReminders?: {
    invoke: (request: unknown) => Promise<unknown>
  }
  readonly darwinCalendar?: {
    invoke: (request: unknown) => Promise<unknown>
  }
  readonly darwinTasks?: {
    invoke: (request: unknown) => Promise<unknown>
  }
  readonly darwinAssistant?: {
    getState: () => Promise<unknown>
    previewState: (state: string) => Promise<{ ok: boolean }>
    subscribeState: (listener: (event: unknown) => void) => string
    unsubscribeState: (subscriptionId: string) => void
  }
  readonly darwinAssistantSession?: {
    getStatus: () => Promise<unknown>
    getUsage: () => Promise<unknown>
    submit: (
      requestId: string,
      content: string
    ) => Promise<{ ok: boolean; requestId?: string; error?: string }>
    listen: (
      requestId: string
    ) => Promise<{ ok: boolean; requestId?: string; error?: string }>
    cancel: (requestId: string) => Promise<{ ok: boolean; error?: string }>
    confirm: (
      requestId: string,
      approved: boolean
    ) => Promise<{ ok: boolean; error?: string }>
    controlMedia: (
      action: 'pause' | 'resume' | 'next' | 'previous'
    ) => Promise<{ ok: boolean; error?: string }>
    subscribeEvents: (listener: (event: unknown) => void) => string
    subscribeStatus: (listener: (event: unknown) => void) => string
    unsubscribe: (subscriptionId: string) => void
  }
  readonly darwinSystemStats?: {
    subscribe: (listener: (event: unknown) => void) => void
    unsubscribe: () => void
  }
  readonly darwinVision?: {
    detect: (image: string) => Promise<
      | {
          protocolVersion: '1.0'
          requestId: string
          ok: true
          detections: Array<{
            label: string
            confidence: number
            x: number
            y: number
            width: number
            height: number
          }>
        }
      | {
          protocolVersion?: '1.0'
          requestId?: string
          ok: false
          error: string
          code?: string
        }
    >
  }
}

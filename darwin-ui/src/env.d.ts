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
    subscribeStatus: (listener: (event: unknown) => void) => string
    unsubscribeStatus: (subscriptionId: string) => void
  }
  readonly darwinReminders?: {
    invoke: (request: unknown) => Promise<unknown>
  }
}

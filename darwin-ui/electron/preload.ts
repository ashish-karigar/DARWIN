import { contextBridge, ipcRenderer } from 'electron'

const darwinHost = Object.freeze({
  versions: Object.freeze({
    chrome: process.versions.chrome,
    electron: process.versions.electron,
    node: process.versions.node
  }),
  credentials: Object.freeze({
    store: (credentialId: string, secret: string) =>
      ipcRenderer.invoke('credentials:store', credentialId, secret),
    has: (credentialId: string) => ipcRenderer.invoke('credentials:has', credentialId),
    remove: (credentialId: string) =>
      ipcRenderer.invoke('credentials:remove', credentialId)
  })
})

const statusListeners = new Map<string, (...args: unknown[]) => void>()
const mediaListeners = new Map<string, (...args: unknown[]) => void>()
let nextStatusListenerId = 1
let nextMediaListenerId = 1
const darwinWebApps = Object.freeze({
  create: (request: unknown) => ipcRenderer.invoke('web-app:create', request),
  update: (request: unknown) => ipcRenderer.invoke('web-app:update', request),
  destroy: (instanceId: string) => ipcRenderer.invoke('web-app:destroy', instanceId),
  navigate: (request: unknown) => ipcRenderer.invoke('web-app:navigate', request),
  controlMedia: (action: 'pause' | 'resume' | 'next' | 'previous') =>
    ipcRenderer.invoke('web-app:media-control', action),
  subscribeStatus: (listener: (event: unknown) => void) => {
    const subscriptionId = `web-status-${nextStatusListenerId++}`
    const handler = (_event: unknown, value: unknown) => listener(value)
    statusListeners.set(subscriptionId, handler)
    ipcRenderer.on('web-app:event', handler)
    return subscriptionId
  },
  unsubscribeStatus: (subscriptionId: string) => {
    const handler = statusListeners.get(subscriptionId)
    if (handler) ipcRenderer.removeListener('web-app:event', handler)
    statusListeners.delete(subscriptionId)
  },
  subscribeMedia: (listener: (event: unknown) => void) => {
    const subscriptionId = `web-media-${nextMediaListenerId++}`
    const handler = (_event: unknown, value: unknown) => listener(value)
    mediaListeners.set(subscriptionId, handler)
    ipcRenderer.on('web-app:media', handler)
    return subscriptionId
  },
  unsubscribeMedia: (subscriptionId: string) => {
    const handler = mediaListeners.get(subscriptionId)
    if (handler) ipcRenderer.removeListener('web-app:media', handler)
    mediaListeners.delete(subscriptionId)
  }
})

const assistantStateListeners = new Map<string, (...args: unknown[]) => void>()
let nextAssistantStateListenerId = 1
const darwinAssistant = Object.freeze({
  getState: () => ipcRenderer.invoke('assistant:get-state'),
  previewState: (state: string) =>
    ipcRenderer.invoke('assistant:preview-state', { state }),
  subscribeState: (listener: (event: unknown) => void) => {
    const subscriptionId = `assistant-state-${nextAssistantStateListenerId++}`
    const handler = (_event: unknown, value: unknown) => listener(value)
    assistantStateListeners.set(subscriptionId, handler)
    ipcRenderer.on('assistant:state', handler)
    return subscriptionId
  },
  unsubscribeState: (subscriptionId: string) => {
    const handler = assistantStateListeners.get(subscriptionId)
    if (handler) ipcRenderer.removeListener('assistant:state', handler)
    assistantStateListeners.delete(subscriptionId)
  }
})

const assistantApiListeners = new Map<string, (...args: unknown[]) => void>()
let nextAssistantApiListenerId = 1
const subscribeAssistantApi = (channel: string, listener: (event: unknown) => void) => {
  const subscriptionId = `assistant-api-${nextAssistantApiListenerId++}`
  const handler = (_event: unknown, value: unknown) => listener(value)
  assistantApiListeners.set(subscriptionId, handler)
  ipcRenderer.on(channel, handler)
  return subscriptionId
}
const darwinAssistantSession = Object.freeze({
  getStatus: () => ipcRenderer.invoke('assistant-api:get-status'),
  getUsage: () => ipcRenderer.invoke('assistant-api:get-usage'),
  submit: (requestId: string, content: string) =>
    ipcRenderer.invoke('assistant-api:submit', { requestId, content }),
  listen: (requestId: string) =>
    ipcRenderer.invoke('assistant-api:listen', { requestId }),
  cancel: (requestId: string) =>
    ipcRenderer.invoke('assistant-api:cancel', { requestId }),
  confirm: (requestId: string, approved: boolean) =>
    ipcRenderer.invoke('assistant-api:confirm', { requestId, approved }),
  controlMedia: (action: 'pause' | 'resume' | 'next' | 'previous') =>
    ipcRenderer.invoke('assistant-api:media-control', action),
  subscribeEvents: (listener: (event: unknown) => void) =>
    subscribeAssistantApi('assistant-api:event', listener),
  subscribeStatus: (listener: (event: unknown) => void) =>
    subscribeAssistantApi('assistant-api:status', listener),
  unsubscribe: (subscriptionId: string) => {
    const handler = assistantApiListeners.get(subscriptionId)
    if (!handler) return
    ipcRenderer.removeListener('assistant-api:event', handler)
    ipcRenderer.removeListener('assistant-api:status', handler)
    assistantApiListeners.delete(subscriptionId)
  }
})

let systemStatsHandler: ((...args: unknown[]) => void) | null = null
const darwinSystemStats = Object.freeze({
  subscribe: (listener: (event: unknown) => void) => {
    if (systemStatsHandler) ipcRenderer.removeListener('system-stats:update', systemStatsHandler)
    systemStatsHandler = (_event: unknown, value: unknown) => listener(value)
    ipcRenderer.on('system-stats:update', systemStatsHandler)
  },
  unsubscribe: () => {
    if (systemStatsHandler) ipcRenderer.removeListener('system-stats:update', systemStatsHandler)
    systemStatsHandler = null
  }
})

contextBridge.exposeInMainWorld('darwinHost', darwinHost)
contextBridge.exposeInMainWorld('darwinWebApps', darwinWebApps)
contextBridge.exposeInMainWorld('darwinAssistant', darwinAssistant)
contextBridge.exposeInMainWorld('darwinAssistantSession', darwinAssistantSession)
contextBridge.exposeInMainWorld('darwinSystemStats', darwinSystemStats)
contextBridge.exposeInMainWorld('darwinVision', {
  detect: (image: string) => ipcRenderer.invoke('vision:detect', { image })
})
contextBridge.exposeInMainWorld('darwinReminders', {
  invoke: (request: unknown) => ipcRenderer.invoke('reminders:invoke', request)
})
contextBridge.exposeInMainWorld('darwinCalendar', {
  invoke: (request: unknown) => ipcRenderer.invoke('calendar:invoke', request)
})
contextBridge.exposeInMainWorld('darwinTasks', {
  invoke: (request: unknown) => ipcRenderer.invoke('tasks:invoke', request)
})

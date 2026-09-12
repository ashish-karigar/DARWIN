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
let nextStatusListenerId = 1
const darwinWebApps = Object.freeze({
  create: (request: unknown) => ipcRenderer.invoke('web-app:create', request),
  update: (request: unknown) => ipcRenderer.invoke('web-app:update', request),
  destroy: (instanceId: string) => ipcRenderer.invoke('web-app:destroy', instanceId),
  navigate: (request: unknown) => ipcRenderer.invoke('web-app:navigate', request),
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

contextBridge.exposeInMainWorld('darwinHost', darwinHost)
contextBridge.exposeInMainWorld('darwinWebApps', darwinWebApps)
contextBridge.exposeInMainWorld('darwinAssistant', darwinAssistant)
contextBridge.exposeInMainWorld('darwinReminders', {
  invoke: (request: unknown) => ipcRenderer.invoke('reminders:invoke', request)
})

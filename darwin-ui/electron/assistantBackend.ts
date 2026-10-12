import { app, BrowserWindow, ipcMain, type IpcMainInvokeEvent } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import { randomBytes, randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { createServer } from 'node:net'
import { resolve } from 'node:path'
import { z } from 'zod'
import { PROTOCOL_VERSION, parseServerMessage } from '../shared/contracts.js'
import { getCredentialEnvironment, subscribeCredentialChanges } from './credentials.js'

const submitSchema = z.object({
  requestId: z.string().uuid(),
  content: z.string().trim().min(1).max(50_000)
})
const requestIdSchema = z.object({ requestId: z.string().uuid() })
const confirmationSchema = requestIdSchema.extend({ approved: z.boolean() })
const mediaControlSchema = z.enum(['pause', 'resume', 'next', 'previous'])
const groqUsageSchema = z.object({
  provider: z.literal('groq'),
  model: z.string().min(1),
  used_tokens: z.number().int().nonnegative(),
  input_tokens: z.number().int().nonnegative(),
  output_tokens: z.number().int().nonnegative(),
  daily_limit_tokens: z.number().int().positive(),
  remaining_tokens: z.number().int().nonnegative(),
  request_count: z.number().int().nonnegative(),
  usage_day: z.string().min(1),
  reset_at: z.string().min(1),
  tracked_since: z.string().nullable(),
  scope: z.literal('darwin-local')
})
type BackendStatus = 'starting' | 'connected' | 'reconnecting' | 'error' | 'stopped'

const wireBase = (type: string, messageId: string = randomUUID()) => ({
  protocolVersion: PROTOCOL_VERSION,
  messageId,
  timestamp: new Date().toISOString(),
  type
})

const availablePort = (): Promise<number> =>
  new Promise((resolvePort, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close((error) => (error ? reject(error) : resolvePort(port)))
    })
  })

export class AssistantBackend {
  readonly #window: BrowserWindow
  readonly #token = randomBytes(32).toString('hex')
  readonly #sessionId = `desktop-${randomUUID()}`
  #process: ChildProcess | null = null
  #socket: WebSocket | null = null
  #status: BackendStatus = 'stopped'
  #stopping = false
  #restartAttempts = 0
  #restartTimer: ReturnType<typeof setTimeout> | null = null
  #stderr = ''
  #port: number | null = null
  #credentialRestartTimer: ReturnType<typeof setTimeout> | null = null
  readonly #unsubscribeCredentialChanges: () => void

  constructor(window: BrowserWindow) {
    this.#window = window
    this.#unsubscribeCredentialChanges = subscribeCredentialChanges(() => {
      if (this.#credentialRestartTimer) clearTimeout(this.#credentialRestartTimer)
      this.#credentialRestartTimer = setTimeout(() => {
        this.#credentialRestartTimer = null
        this.#restartForCredentials()
      }, 500)
    })
  }

  start() {
    if (this.#process || this.#stopping) return
    void this.#launch()
  }

  current() {
    return {
      status: this.#status,
      connected: this.#status === 'connected',
      sessionId: this.#sessionId
    }
  }

  submit(value: unknown) {
    const request = submitSchema.parse(value)
    this.#send({
      ...wireBase('assistant.request', request.requestId),
      sessionId: this.#sessionId,
      content: request.content
    })
    return { ok: true, requestId: request.requestId }
  }

  listen(value: unknown) {
    const request = requestIdSchema.parse(value)
    this.#send({
      ...wireBase('assistant.listen', request.requestId),
      sessionId: this.#sessionId
    })
    return { ok: true, requestId: request.requestId }
  }

  cancel(value: unknown) {
    const request = requestIdSchema.parse(value)
    this.#send({
      ...wireBase('assistant.cancel'),
      requestId: request.requestId
    })
    return { ok: true }
  }

  confirm(value: unknown) {
    const request = confirmationSchema.parse(value)
    this.#send({
      ...wireBase('confirmation.response'),
      requestId: request.requestId,
      approved: request.approved
    })
    return { ok: true }
  }

  controlMedia(value: unknown) {
    const action = mediaControlSchema.parse(value)
    this.#send({ ...wireBase('media.control'), action })
    return { ok: true }
  }

  async usage() {
    if (!this.#port || this.#status !== 'connected') {
      return { available: false }
    }
    try {
      const response = await fetch(`http://127.0.0.1:${this.#port}/usage/groq`, {
        headers: { 'x-darwin-token': this.#token }
      })
      if (!response.ok) return { available: false }
      const parsed = groqUsageSchema.safeParse(await response.json())
      return parsed.success ? { available: true, ...parsed.data } : { available: false }
    } catch {
      return { available: false }
    }
  }

  stop() {
    this.#stopping = true
    if (this.#restartTimer) clearTimeout(this.#restartTimer)
    if (this.#credentialRestartTimer) clearTimeout(this.#credentialRestartTimer)
    this.#restartTimer = null
    this.#credentialRestartTimer = null
    this.#unsubscribeCredentialChanges()
    this.#socket?.close()
    this.#socket = null
    this.#process?.kill()
    this.#process = null
    this.#port = null
    this.#publishStatus('stopped')
  }

  async #launch() {
    this.#publishStatus(this.#restartAttempts ? 'reconnecting' : 'starting')
    try {
      const port = await availablePort()
      if (this.#stopping) return
      const root = this.#resolveRoot()
      const credentialEnvironment = await getCredentialEnvironment().catch(() => ({}))
      const child = spawn(
        this.#resolvePython(root),
        ['-m', 'app.services.assistant_api'],
        {
          cwd: root,
          env: {
            ...process.env,
            ...credentialEnvironment,
            DARWIN_API_PORT: String(port),
            DARWIN_API_TOKEN: this.#token,
            PYTHONPATH: resolve(root, 'src')
          },
          stdio: ['ignore', 'ignore', 'pipe']
        }
      )
      this.#process = child
      child.stderr?.setEncoding('utf8')
      child.stderr?.on('data', (chunk: string) => {
        this.#stderr = `${this.#stderr}${chunk}`.slice(-2_000)
      })
      child.on('error', () => this.#scheduleRestart())
      child.on('exit', () => {
        if (this.#process !== child) return
        this.#process = null
        this.#socket = null
        this.#port = null
        if (!this.#stopping) this.#scheduleRestart()
      })
      await this.#waitUntilReady(port)
      if (this.#stopping || this.#process !== child) return
      this.#port = port
      this.#connect(port)
    } catch {
      this.#process?.kill()
      this.#process = null
      this.#scheduleRestart()
    }
  }

  async #waitUntilReady(port: number) {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      if (this.#stopping) throw new Error('stopped')
      try {
        const response = await fetch(`http://127.0.0.1:${port}/health`, {
          headers: { 'x-darwin-token': this.#token }
        })
        if (response.ok) return
      } catch {
        // The child is still starting.
      }
      await new Promise((resolveWait) => setTimeout(resolveWait, 250))
    }
    throw new Error('backend readiness timed out')
  }

  #connect(port: number) {
    const socket = new WebSocket(`ws://127.0.0.1:${port}/ws?token=${this.#token}`)
    this.#socket = socket
    socket.addEventListener('open', () => {
      this.#send({ ...wireBase('session.hello'), clientName: 'DARWIN UI' })
    })
    socket.addEventListener('message', (event) => {
      try {
        const message = parseServerMessage(JSON.parse(String(event.data)) as unknown)
        if (message.type === 'session.ready') {
          this.#restartAttempts = 0
          this.#publishStatus('connected')
          this.#send({
            ...wireBase('assistant.wake'),
            sessionId: this.#sessionId,
            enabled: true
          })
        }
        this.#publish('assistant-api:event', message)
      } catch {
        // Invalid backend messages never reach the renderer.
      }
    })
    socket.addEventListener('close', () => {
      if (this.#socket === socket && !this.#stopping && this.#process)
        this.#process.kill()
    })
    socket.addEventListener('error', () => {
      if (this.#socket === socket && !this.#stopping && this.#process)
        this.#process.kill()
    })
  }

  #restartForCredentials() {
    if (this.#stopping) return
    const child = this.#process
    const socket = this.#socket
    this.#process = null
    this.#socket = null
    this.#port = null
    this.#restartAttempts = 0
    if (this.#restartTimer) clearTimeout(this.#restartTimer)
    this.#restartTimer = null
    socket?.close()
    child?.kill()
    void this.#launch()
  }

  #send(message: object) {
    if (!this.#socket || this.#socket.readyState !== WebSocket.OPEN) {
      throw new Error('DARWIN assistant is not connected')
    }
    this.#socket.send(JSON.stringify(message))
  }

  #scheduleRestart() {
    if (this.#stopping || this.#restartTimer) return
    if (this.#restartAttempts >= 3) {
      console.error('DARWIN assistant backend failed to start.', this.#stderr.trim())
      this.#publishStatus('error')
      return
    }
    const delays = [500, 1_500, 3_000]
    const delay = delays[this.#restartAttempts] ?? 3_000
    this.#restartAttempts += 1
    this.#publishStatus('reconnecting')
    this.#restartTimer = setTimeout(() => {
      this.#restartTimer = null
      void this.#launch()
    }, delay)
  }

  #publishStatus(status: BackendStatus) {
    this.#status = status
    this.#publish('assistant-api:status', {
      status,
      connected: status === 'connected',
      sessionId: this.#sessionId
    })
  }

  #publish(channel: string, value: unknown) {
    if (this.#window.isDestroyed() || this.#window.webContents.isDestroyed()) return
    this.#window.webContents.send(channel, value)
  }

  #resolvePython(root: string) {
    const candidates = [
      process.env.DARWIN_PYTHON,
      process.env.CONDA_PREFIX
        ? resolve(process.env.CONDA_PREFIX, 'bin/python')
        : undefined,
      resolve(root, '.venv/bin/python'),
      '/opt/homebrew/anaconda3/envs/DARWIN/bin/python',
      'python3'
    ].filter((candidate): candidate is string => Boolean(candidate))
    return candidates.find(
      (candidate) => !candidate.includes('/') || existsSync(candidate)
    )!
  }

  #resolveRoot() {
    const candidates = [
      process.env.DARWIN_PROJECT_ROOT,
      app.isPackaged ? resolve(process.resourcesPath, 'darwin-backend') : undefined,
      resolve(__dirname, '../../..')
    ].filter((candidate): candidate is string => Boolean(candidate))
    const root = candidates.find((candidate) => existsSync(resolve(candidate, 'src/app')))
    if (!root) throw new Error('DARWIN backend resources are unavailable')
    return root
  }
}

export const registerAssistantBackend = (window: BrowserWindow) => {
  for (const channel of [
    'assistant-api:get-status',
    'assistant-api:get-usage',
    'assistant-api:submit',
    'assistant-api:listen',
    'assistant-api:cancel',
    'assistant-api:confirm',
    'assistant-api:media-control'
  ])
    ipcMain.removeHandler(channel)
  const backend = new AssistantBackend(window)
  const guarded =
    (operation: (value: unknown) => unknown) =>
    (event: IpcMainInvokeEvent, value: unknown) => {
      if (event.sender !== window.webContents) {
        return { ok: false, error: 'Unauthorized assistant request' }
      }
      try {
        return operation(value)
      } catch (error) {
        return {
          ok: false,
          error: error instanceof Error ? error.message : 'Request failed'
        }
      }
    }
  ipcMain.handle('assistant-api:get-status', (event) =>
    event.sender === window.webContents
      ? backend.current()
      : { status: 'error', connected: false }
  )
  ipcMain.handle('assistant-api:get-usage', (event) =>
    event.sender === window.webContents ? backend.usage() : { available: false }
  )
  ipcMain.handle(
    'assistant-api:submit',
    guarded((value) => backend.submit(value))
  )
  ipcMain.handle(
    'assistant-api:listen',
    guarded((value) => backend.listen(value))
  )
  ipcMain.handle(
    'assistant-api:cancel',
    guarded((value) => backend.cancel(value))
  )
  ipcMain.handle(
    'assistant-api:confirm',
    guarded((value) => backend.confirm(value))
  )
  ipcMain.handle(
    'assistant-api:media-control',
    guarded((value) => backend.controlMedia(value))
  )
  backend.start()
  window.on('closed', () => backend.stop())
  return backend
}

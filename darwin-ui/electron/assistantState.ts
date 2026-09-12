import { BrowserWindow, ipcMain } from 'electron'
import { createHash, randomBytes } from 'node:crypto'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { z } from 'zod'

const assistantStateSchema = z.enum([
  'idle',
  'listening',
  'transcribing',
  'thinking',
  'speaking',
  'error'
])

const serviceMessageSchema = z.discriminatedUnion('type', [
  z.object({
    protocolVersion: z.literal('1.0'),
    type: z.literal('assistant.state'),
    state: assistantStateSchema
  }),
  z.object({
    protocolVersion: z.literal('1.0'),
    type: z.literal('assistant.audio-level'),
    level: z.number().min(0).max(1)
  })
])

const previewSchema = z.object({ state: assistantStateSchema })

export type AssistantState = z.infer<typeof assistantStateSchema>

export class AssistantStateService {
  readonly #window: BrowserWindow
  readonly #token = randomBytes(32).toString('hex')
  #process: ChildProcessWithoutNullStreams | null = null
  #buffer = ''
  #state: AssistantState = 'idle'
  #audioLevel = 0
  #connected = false
  #stderr = ''
  #stopping = false

  constructor(window: BrowserWindow) {
    this.#window = window
  }

  start() {
    if (this.#process) return
    const root = resolve(__dirname, '../../..')
    const python = this.#resolvePython(root)
    const child = spawn(python, ['-m', 'app.services.ui_state'], {
      cwd: root,
      env: {
        ...process.env,
        DARWIN_UI_STATE_TOKEN: this.#token,
        PYTHONPATH: resolve(root, 'src')
      },
      stdio: ['pipe', 'pipe', 'pipe']
    })
    this.#process = child
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => this.#consume(chunk))
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk: string) => {
      this.#stderr = `${this.#stderr}${chunk}`.slice(-2_000)
    })
    child.on('error', () => this.#publish('error', false))
    child.on('exit', (code) => {
      if (this.#process === child) this.#process = null
      if (this.#stopping || this.#window.isDestroyed()) return
      if (!this.#connected || code !== 0) {
        console.error('DARWIN Python state service stopped.', this.#stderr.trim())
        this.#publish('error', false)
      }
    })
  }

  preview(value: unknown) {
    const request = previewSchema.parse(value)
    if (!this.#connected || !this.#process?.stdin.writable) return { ok: false }
    this.#process.stdin.write(
      `${JSON.stringify({
        token: this.#token,
        type: 'assistant.state.preview',
        state: request.state
      })}\n`
    )
    return { ok: true }
  }

  current() {
    return {
      state: this.#state,
      connected: this.#connected,
      audioLevel: this.#audioLevel
    }
  }

  stop() {
    this.#stopping = true
    this.#process?.kill()
    this.#process = null
  }

  #consume(chunk: string) {
    this.#buffer += chunk
    const lines = this.#buffer.split('\n')
    this.#buffer = lines.pop() ?? ''
    for (const line of lines) {
      try {
        const message = serviceMessageSchema.parse(JSON.parse(line) as unknown)
        if (message.type === 'assistant.state') this.#publish(message.state, true)
        else this.#publishAudioLevel(message.level)
      } catch {
        // The renderer only receives validated state messages.
      }
    }
  }

  #publish(state: AssistantState, connected = this.#connected) {
    this.#state = state
    this.#connected = connected
    if (this.#window.isDestroyed() || this.#window.webContents.isDestroyed()) return
    this.#window.webContents.send('assistant:state', {
      state,
      connected,
      source: createHash('sha256').update(this.#token).digest('hex').slice(0, 12)
    })
  }

  #publishAudioLevel(audioLevel: number) {
    this.#audioLevel = audioLevel
    if (this.#window.isDestroyed() || this.#window.webContents.isDestroyed()) return
    this.#window.webContents.send('assistant:state', {
      audioLevel,
      source: createHash('sha256').update(this.#token).digest('hex').slice(0, 12)
    })
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
}

export const registerAssistantStateService = (window: BrowserWindow) => {
  ipcMain.removeHandler('assistant:preview-state')
  ipcMain.removeHandler('assistant:get-state')
  const service = new AssistantStateService(window)
  ipcMain.handle('assistant:preview-state', (_event, value) => {
    try {
      return service.preview(value)
    } catch {
      return { ok: false }
    }
  })
  ipcMain.handle('assistant:get-state', () => service.current())
  service.start()
  window.on('closed', () => service.stop())
  return service
}

import { BrowserWindow, ipcMain } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { z } from 'zod'

const requestSchema = z.object({
  image: z.string().min(1).max(2_000_000)
})

const detectionSchema = z.object({
  label: z.string().trim().min(1).max(80),
  confidence: z.number().min(0).max(1),
  x: z.number().min(0).max(1),
  y: z.number().min(0).max(1),
  width: z.number().min(0).max(1),
  height: z.number().min(0).max(1)
})

const responseSchema = z.discriminatedUnion('ok', [
  z.object({
    protocolVersion: z.literal('1.0'),
    requestId: z.string(),
    ok: z.literal(true),
    detections: z.array(detectionSchema).max(50)
  }),
  z.object({
    protocolVersion: z.literal('1.0'),
    requestId: z.string(),
    ok: z.literal(false),
    error: z.string().max(300),
    code: z.string().max(80).optional()
  })
])

type VisionResponse = z.infer<typeof responseSchema>
type PendingRequest = {
  resolve: (value: VisionResponse) => void
  timer: ReturnType<typeof setTimeout>
}

class VisionService {
  #process: ChildProcessWithoutNullStreams | null = null
  #buffer = ''
  #pending = new Map<string, PendingRequest>()

  async detect(value: unknown): Promise<VisionResponse> {
    const { image } = requestSchema.parse(value)
    const child = this.#start()
    const requestId = randomUUID()
    return new Promise((resolveRequest) => {
      const timer = setTimeout(() => {
        this.#pending.delete(requestId)
        resolveRequest({
          protocolVersion: '1.0',
          requestId,
          ok: false,
          error: 'Object detection timed out',
          code: 'timeout'
        })
      }, 30_000)
      this.#pending.set(requestId, { resolve: resolveRequest, timer })
      child.stdin.write(
        `${JSON.stringify({ protocolVersion: '1.0', requestId, type: 'vision.detect', image })}\n`
      )
    })
  }

  stop() {
    this.#process?.kill()
    this.#process = null
    this.#failPending('Object detection stopped', 'service_stopped')
  }

  #start() {
    if (this.#process?.stdin.writable) return this.#process
    const root = resolve(__dirname, '../../..')
    const child = spawn(this.#resolvePython(root), ['-m', 'app.services.vision'], {
      cwd: root,
      env: { ...process.env, PYTHONPATH: resolve(root, 'src') },
      stdio: ['pipe', 'pipe', 'pipe']
    })
    this.#process = child
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => this.#consume(chunk))
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk: string) => {
      const message = chunk.trim()
      if (message) console.warn('DARWIN vision:', message.slice(-500))
    })
    child.on('error', () =>
      this.#failPending('Object detection could not start', 'startup_failed')
    )
    child.on('exit', () => {
      if (this.#process === child) this.#process = null
      this.#failPending('Object detection stopped unexpectedly', 'service_stopped')
    })
    return child
  }

  #consume(chunk: string) {
    this.#buffer += chunk
    const lines = this.#buffer.split('\n')
    this.#buffer = lines.pop() ?? ''
    for (const line of lines) {
      try {
        const response = responseSchema.parse(JSON.parse(line) as unknown)
        const pending = this.#pending.get(response.requestId)
        if (!pending) continue
        clearTimeout(pending.timer)
        this.#pending.delete(response.requestId)
        pending.resolve(response)
      } catch {
        // Only validated detection data crosses into the renderer.
      }
    }
  }

  #failPending(error: string, code: string) {
    for (const [requestId, pending] of this.#pending) {
      clearTimeout(pending.timer)
      pending.resolve({ protocolVersion: '1.0', requestId, ok: false, error, code })
    }
    this.#pending.clear()
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

export const registerVisionHandlers = (window: BrowserWindow) => {
  ipcMain.removeHandler('vision:detect')
  const service = new VisionService()
  ipcMain.handle('vision:detect', (event, value) => {
    if (event.sender !== window.webContents) {
      return { ok: false, error: 'Unauthorized vision request', code: 'unauthorized' }
    }
    return service.detect(value).catch(() => ({
      ok: false,
      error: 'Invalid vision request',
      code: 'invalid_request'
    }))
  })
  window.on('closed', () => service.stop())
  return service
}

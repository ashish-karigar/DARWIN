import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { access, mkdtemp, readFile, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { z } from 'zod'

const ruleSchema = z.object({
  id: z.string().min(1).max(100),
  sender: z.string().trim().min(1).max(500),
  mailbox: z.string().trim().min(1).max(200),
  enabled: z.boolean()
})

const actionSchema = z.discriminatedUnion('action', [
  z.object({ action: z.literal('requestMailAccess') }),
  z.object({ action: z.literal('openMailSettings') }),
  z.object({
    action: z.literal('scan'),
    rules: z.array(ruleSchema).max(20),
    seenMessageIds: z.array(z.string().min(1).max(1000)).max(2_000),
    model: z.string().regex(/^[a-zA-Z0-9_.:-]{1,100}$/)
  })
])

const mailMessageSchema = z.object({
  id: z.string().min(1).max(1000),
  sender: z.string().max(500),
  subject: z.string().max(500),
  receivedAt: z.string().max(200),
  account: z.string().max(200),
  mailbox: z.string().max(200),
  body: z.string().max(50_000)
})

const extractionSchema = z.object({
  isTask: z.boolean(),
  title: z.string().max(500),
  dueDate: z.string().nullable(),
  priority: z.union([z.literal(0), z.literal(1), z.literal(5), z.literal(9)]),
  notes: z.string().max(5_000),
  confidence: z.number().min(0).max(1),
  reason: z.string().max(1_000)
})

const workerResponseSchema = z.discriminatedUnion('ok', [
  z.object({
    protocolVersion: z.literal('1.0'),
    requestId: z.string(),
    ok: z.literal(true),
    extraction: extractionSchema
  }),
  z.object({
    protocolVersion: z.literal('1.0'),
    requestId: z.string(),
    ok: z.literal(false),
    error: z.string().max(300),
    code: z.string().max(80).optional()
  })
])

type WorkerResponse = z.infer<typeof workerResponseSchema>
type MailMessage = z.infer<typeof mailMessageSchema>
type PendingRequest = {
  resolve: (value: WorkerResponse) => void
  timer: ReturnType<typeof setTimeout>
}

class TaskExtractionService {
  #process: ChildProcessWithoutNullStreams | null = null
  #buffer = ''
  #pending = new Map<string, PendingRequest>()

  async extract(message: MailMessage, model: string): Promise<WorkerResponse> {
    const child = this.#start()
    const requestId = randomUUID()
    return new Promise((resolveRequest) => {
      const timer = setTimeout(() => {
        this.#pending.delete(requestId)
        resolveRequest({
          protocolVersion: '1.0',
          requestId,
          ok: false,
          error: 'Local task extraction timed out',
          code: 'timeout'
        })
      }, 110_000)
      this.#pending.set(requestId, { resolve: resolveRequest, timer })
      child.stdin.write(
        `${JSON.stringify({
          protocolVersion: '1.0',
          requestId,
          type: 'task.extract',
          model,
          sender: message.sender,
          subject: message.subject,
          body: message.body
        })}\n`
      )
    })
  }

  stop() {
    this.#process?.kill()
    this.#process = null
    this.#failPending('Task extraction stopped', 'service_stopped')
  }

  #start() {
    if (this.#process?.stdin.writable) return this.#process
    const root = resolve(__dirname, '../../..')
    const child = spawn(this.#resolvePython(root), ['-m', 'app.services.task_extraction'], {
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
      if (message) console.warn('DARWIN tasks:', message.slice(-500))
    })
    child.on('error', () =>
      this.#failPending('Local task extraction could not start', 'startup_failed')
    )
    child.on('exit', () => {
      if (this.#process === child) this.#process = null
      this.#failPending('Local task extraction stopped unexpectedly', 'service_stopped')
    })
    return child
  }

  #consume(chunk: string) {
    this.#buffer += chunk
    const lines = this.#buffer.split('\n')
    this.#buffer = lines.pop() ?? ''
    for (const line of lines) {
      try {
        const response = workerResponseSchema.parse(JSON.parse(line) as unknown)
        const pending = this.#pending.get(response.requestId)
        if (!pending) continue
        clearTimeout(pending.timer)
        this.#pending.delete(response.requestId)
        pending.resolve(response)
      } catch {
        // Unvalidated worker output never crosses into the renderer.
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
      process.env.CONDA_PREFIX ? resolve(process.env.CONDA_PREFIX, 'bin/python') : undefined,
      resolve(root, '.venv/bin/python'),
      '/opt/homebrew/anaconda3/envs/DARWIN/bin/python',
      'python3'
    ].filter((candidate): candidate is string => Boolean(candidate))
    return candidates.find((candidate) => !candidate.includes('/') || existsSync(candidate))!
  }
}

const helperBundles = () => [
  join(app.getAppPath(), 'native/bin/DARWIN Mail Bridge.app'),
  join(process.cwd(), 'native/bin/DARWIN Mail Bridge.app'),
  join(process.resourcesPath, 'native/DARWIN Mail Bridge.app')
]

const findHelper = async () => {
  for (const path of helperBundles()) {
    try {
      await access(path)
      return path
    } catch {
      // Try the next development or packaged location.
    }
  }
  return null
}

const invokeMailHelper = async (request: unknown): Promise<unknown> => {
  const bundle = await findHelper()
  if (!bundle) return { ok: false, error: 'mail_helper_unavailable' }
  const responseDirectory = await mkdtemp(join(tmpdir(), 'darwin-mail-'))
  const responsePath = join(responseDirectory, 'response.json')
  return new Promise((resolveRequest) => {
    const child = spawn(
      '/usr/bin/open',
      ['-n', bundle, '--args', JSON.stringify(request), responsePath],
      { stdio: ['ignore', 'ignore', 'pipe'] }
    )
    let stderr = ''
    let settled = false
    const finish = (result: unknown) => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      clearInterval(responsePoll)
      void rm(responseDirectory, { recursive: true, force: true })
      resolveRequest(result)
    }
    const timeout = setTimeout(() => {
      child.kill()
      finish({ ok: false, error: 'mail_request_timed_out' })
    }, 60_000)
    const responsePoll = setInterval(async () => {
      try {
        const output = await readFile(responsePath, 'utf8')
        finish(JSON.parse(output) as unknown)
      } catch {
        // The helper has not written its atomic response yet.
      }
    }, 100)
    child.stderr.setEncoding('utf8').on('data', (chunk) => {
      stderr += chunk
    })
    child.on('error', () => finish({ ok: false, error: 'mail_helper_failed' }))
    child.on('close', (code) => {
      if (code !== 0) finish({ ok: false, error: stderr || 'mail_helper_launch_failed' })
    })
  })
}

const scanMessages = async (
  service: TaskExtractionService,
  command: Extract<z.infer<typeof actionSchema>, { action: 'scan' }>
) => {
  const seen = new Set(command.seenMessageIds)
  const processedMessageIds: string[] = []
  const candidates: Array<Record<string, unknown>> = []
  for (const rule of command.rules.filter((item) => item.enabled)) {
    const raw = await invokeMailHelper({
      action: 'scan',
      sender: rule.sender,
      mailbox: rule.mailbox,
      maxMessages: 10
    })
    const result = z
      .union([
        z.object({ ok: z.literal(true), messages: z.array(mailMessageSchema).max(25) }),
        z.object({ ok: z.literal(false), error: z.string().max(500) })
      ])
      .parse(raw)
    if (!result.ok) return { ok: false, error: result.error }
    for (const message of result.messages) {
      if (seen.has(message.id)) continue
      seen.add(message.id)
      processedMessageIds.push(message.id)
      const classified = await service.extract(message, command.model)
      if (!classified.ok) {
        return { ok: false, error: classified.error, code: classified.code }
      }
      if (!classified.extraction.isTask) continue
      candidates.push({
        id: randomUUID(),
        messageId: message.id,
        sender: message.sender,
        subject: message.subject,
        receivedAt: message.receivedAt,
        account: message.account,
        mailbox: message.mailbox,
        ...classified.extraction
      })
    }
  }
  return { ok: true, candidates, processedMessageIds }
}

export const registerTaskHandlers = (window: BrowserWindow) => {
  ipcMain.removeHandler('tasks:invoke')
  const service = new TaskExtractionService()
  ipcMain.handle('tasks:invoke', async (event, value) => {
    if (event.sender !== window.webContents) {
      return { ok: false, error: 'unauthorized' }
    }
    try {
      const command = actionSchema.parse(value)
      if (command.action === 'openMailSettings') {
        await shell.openExternal(
          'x-apple.systempreferences:com.apple.preference.security?Privacy_Automation'
        )
        return { ok: true }
      }
      if (command.action === 'requestMailAccess') {
        return invokeMailHelper({ action: 'requestAccess' })
      }
      return scanMessages(service, command)
    } catch {
      return { ok: false, error: 'invalid_task_request' }
    }
  })
  window.on('closed', () => service.stop())
  return service
}

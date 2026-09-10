import { app, ipcMain, shell } from 'electron'
import { spawn } from 'node:child_process'
import { access, mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { z } from 'zod'

const actionSchema = z.discriminatedUnion('action', [
  z.object({ action: z.literal('status') }),
  z.object({ action: z.literal('requestAccess') }),
  z.object({ action: z.literal('openSettings') }),
  z.object({ action: z.literal('list') }),
  z.object({
    action: z.literal('create'),
    title: z.string().trim().min(1).max(500),
    dueDate: z.iso.datetime().nullable().optional(),
    calendarId: z.string().min(1).max(1000).optional()
  }),
  z.object({
    action: z.literal('complete'),
    id: z.string().min(1).max(1000),
    completed: z.boolean()
  }),
  z.object({
    action: z.literal('update'),
    id: z.string().min(1).max(1000),
    title: z.string().trim().min(1).max(500),
    notes: z.string().max(5000),
    dueDate: z.union([z.iso.datetime(), z.literal('')]),
    calendarId: z.string().min(1).max(1000),
    priority: z.number().int().min(0).max(9),
    recurrence: z.enum(['', 'daily', 'weekly', 'monthly', 'yearly'])
  }),
  z.object({ action: z.literal('delete'), id: z.string().min(1).max(1000) })
])

const helperBundles = () => [
  join(app.getAppPath(), 'native/bin/DARWIN Reminders Bridge.app'),
  join(process.cwd(), 'native/bin/DARWIN Reminders Bridge.app'),
  join(process.resourcesPath, 'native/DARWIN Reminders Bridge.app')
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

const invokeHelper = async (request: unknown): Promise<unknown> => {
  const command = actionSchema.parse(request)
  if (command.action === 'openSettings') {
    await shell.openExternal(
      'x-apple.systempreferences:com.apple.preference.security?Privacy_Reminders'
    )
    return { ok: true }
  }
  const bundle = await findHelper()
  if (!bundle) return { ok: false, error: 'helper_unavailable' }

  const responseDirectory = await mkdtemp(join(tmpdir(), 'darwin-reminders-'))
  const responsePath = join(responseDirectory, 'response.json')
  return new Promise((resolve) => {
    const child = spawn(
      '/usr/bin/open',
      ['-n', bundle, '--args', JSON.stringify(command), responsePath],
      { stdio: ['ignore', 'ignore', 'pipe'] }
    )
    let error = ''
    let settled = false
    const finish = (result: unknown) => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      clearInterval(responsePoll)
      void rm(responseDirectory, { recursive: true, force: true })
      resolve(result)
    }
    const timeout = setTimeout(() => {
      child.kill()
      finish({ ok: false, error: 'permission_request_timed_out' })
    }, 30_000)
    const responsePoll = setInterval(async () => {
      try {
        const output = await readFile(responsePath, 'utf8')
        finish(JSON.parse(output))
      } catch {
        // The launched helper has not written its atomic response yet.
      }
    }, 100)
    child.stderr.setEncoding('utf8').on('data', (chunk) => {
      error += chunk
    })
    child.on('error', () => finish({ ok: false, error: 'helper_failed' }))
    child.on('close', (code) => {
      if (code !== 0) finish({ ok: false, error: error || 'helper_launch_failed' })
    })
  })
}

export const registerReminderHandlers = () => {
  ipcMain.removeHandler('reminders:invoke')
  ipcMain.handle('reminders:invoke', (_event, request) => invokeHelper(request))
}

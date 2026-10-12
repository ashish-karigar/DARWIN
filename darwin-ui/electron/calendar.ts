import { app, ipcMain, shell } from 'electron'
import { spawn } from 'node:child_process'
import { access, mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { z } from 'zod'

const id = z.string().min(1).max(1000)
const eventFields = {
  title: z.string().trim().min(1).max(500),
  startDate: z.iso.datetime(),
  endDate: z.iso.datetime(),
  calendarId: id,
  notes: z.string().max(5000).optional(),
  location: z.string().max(1000).optional(),
  allDay: z.boolean().optional()
}
const actionSchema = z.discriminatedUnion('action', [
  z.object({ action: z.literal('status') }),
  z.object({ action: z.literal('requestAccess') }),
  z.object({ action: z.literal('openSettings') }),
  z.object({ action: z.literal('list'), rangeStart: z.iso.datetime(), rangeEnd: z.iso.datetime() }),
  z.object({ action: z.literal('create'), ...eventFields }),
  z.object({ action: z.literal('update'), id, ...eventFields }),
  z.object({ action: z.literal('delete'), id })
])

const bundles = () => [
  join(app.getAppPath(), 'native/bin/DARWIN Calendar Bridge.app'),
  join(process.cwd(), 'native/bin/DARWIN Calendar Bridge.app'),
  join(process.resourcesPath, 'native/DARWIN Calendar Bridge.app')
]

const findHelper = async () => {
  for (const path of bundles()) {
    try { await access(path); return path } catch { /* Try the next path. */ }
  }
  return null
}

const invoke = async (request: unknown): Promise<unknown> => {
  const command = actionSchema.parse(request)
  if (command.action === 'openSettings') {
    await shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars')
    return { ok: true }
  }
  const bundle = await findHelper()
  if (!bundle) return { ok: false, error: 'helper_unavailable' }
  const directory = await mkdtemp(join(tmpdir(), 'darwin-calendar-'))
  const responsePath = join(directory, 'response.json')
  return new Promise((resolve) => {
    const child = spawn('/usr/bin/open', ['-n', bundle, '--args', JSON.stringify(command), responsePath], { stdio: ['ignore', 'ignore', 'pipe'] })
    let settled = false
    const finish = (value: unknown) => {
      if (settled) return
      settled = true; clearTimeout(timeout); clearInterval(poll)
      void rm(directory, { recursive: true, force: true }); resolve(value)
    }
    const timeout = setTimeout(() => { child.kill(); finish({ ok: false, error: 'request_timed_out' }) }, 30_000)
    const poll = setInterval(async () => {
      try { finish(JSON.parse(await readFile(responsePath, 'utf8'))) } catch { /* Waiting. */ }
    }, 100)
    child.on('error', () => finish({ ok: false, error: 'helper_failed' }))
    child.on('close', (code) => { if (code !== 0) finish({ ok: false, error: 'helper_launch_failed' }) })
  })
}

export const registerCalendarHandlers = () => {
  ipcMain.removeHandler('calendar:invoke')
  ipcMain.handle('calendar:invoke', (_event, request) =>
    invoke(request).catch(() => ({ ok: false, error: 'invalid_request' }))
  )
}

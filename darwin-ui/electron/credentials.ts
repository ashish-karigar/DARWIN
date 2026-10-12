import { app, ipcMain, safeStorage } from 'electron'
import { readFile, rename, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

const CREDENTIAL_ENVIRONMENT = {
  'groq.apiKey': 'GROQ_API_KEY',
  'fishAudio.apiKey': 'FISH_API_KEY',
  'fishAudio.voiceId': 'FISH_VOICE_ID',
  'spotify.clientId': 'SPOTIFY_CLIENT_ID',
  'spotify.redirectUri': 'SPOTIFY_REDIRECT_URI',
  'spotify.deviceName': 'SPOTIFY_DEVICE_NAME',
  'langsmith.apiKey': 'LANGSMITH_API_KEY',
  'langsmith.project': 'LANGSMITH_PROJECT',
  'langsmith.tracing': 'DARWIN_LANGSMITH_TRACING',
  'huggingFace.token': 'HF_TOKEN',
  'llamaCloud.apiKey': 'LLAMA_CLOUD_API_KEY'
} as const

const ALLOWED_CREDENTIALS = new Set(Object.keys(CREDENTIAL_ENVIRONMENT))
const changeListeners = new Set<() => void>()

interface CredentialFile {
  version: 1
  credentials: Record<string, string>
}

export interface CredentialResult {
  ok: boolean
  error?: 'invalid_id' | 'secure_storage_unavailable' | 'storage_error'
}

const credentialPath = () => join(app.getPath('userData'), 'darwin-credentials.json')

const parseEnvironment = (source: string): Record<string, string> => {
  const environment: Record<string, string> = {}

  for (const line of source.split(/\r?\n/)) {
    const match = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/)
    if (!match) continue

    const [, name, rawValue] = match
    if (!name || rawValue === undefined) continue
    let value = rawValue.trim()
    const quote = value[0]
    if ((quote === '"' || quote === "'") && value.endsWith(quote)) {
      value = value.slice(1, -1)
    } else {
      value = value.replace(/\s+#.*$/, '').trim()
    }
    environment[name] = value
  }

  return environment
}

const readProjectEnvironment = async (): Promise<Record<string, string>> => {
  const paths = new Set([
    join(process.cwd(), '.env'),
    join(process.cwd(), '..', '.env'),
    join(app.getAppPath(), '.env'),
    join(app.getAppPath(), '..', '.env')
  ])
  const environment: Record<string, string> = {}

  for (const path of paths) {
    try {
      Object.assign(environment, parseEnvironment(await readFile(path, 'utf8')))
    } catch {
      // A project can legitimately omit any of these optional .env locations.
    }
  }

  return environment
}

const readCredentials = async (): Promise<CredentialFile> => {
  try {
    const parsed = JSON.parse(await readFile(credentialPath(), 'utf8')) as CredentialFile
    return parsed.version === 1 && typeof parsed.credentials === 'object'
      ? parsed
      : { version: 1, credentials: {} }
  } catch {
    return { version: 1, credentials: {} }
  }
}

const writeCredentials = async (file: CredentialFile) => {
  const path = credentialPath()
  const temporaryPath = `${path}.tmp`
  await writeFile(temporaryPath, JSON.stringify(file), { encoding: 'utf8', mode: 0o600 })
  await rename(temporaryPath, path)
}

export const getCredentialEnvironment = async (): Promise<Record<string, string>> => {
  if (!safeStorage.isEncryptionAvailable()) return {}
  const file = await readCredentials()
  const environment: Record<string, string> = {}
  for (const [credentialId, environmentName] of Object.entries(CREDENTIAL_ENVIRONMENT)) {
    const encrypted = file.credentials[credentialId]
    if (!encrypted) continue
    try {
      environment[environmentName] = safeStorage.decryptString(
        Buffer.from(encrypted, 'base64')
      )
    } catch {
      // One damaged entry must not prevent the remaining services from starting.
    }
  }
  return environment
}

const hasEffectiveCredential = async (credentialId: string): Promise<boolean> => {
  const environmentName =
    CREDENTIAL_ENVIRONMENT[credentialId as keyof typeof CREDENTIAL_ENVIRONMENT]
  if (!environmentName) return false

  const file = await readCredentials()
  if (file.credentials[credentialId]) return true
  if (process.env[environmentName]?.trim()) return true

  const projectEnvironment = await readProjectEnvironment()
  return Boolean(projectEnvironment[environmentName]?.trim())
}

export const subscribeCredentialChanges = (listener: () => void) => {
  changeListeners.add(listener)
  return () => changeListeners.delete(listener)
}

const publishCredentialChange = () => {
  for (const listener of changeListeners) listener()
}

export const registerCredentialHandlers = () => {
  ipcMain.handle(
    'credentials:store',
    async (_event, credentialId: unknown, secret: unknown): Promise<CredentialResult> => {
      if (
        typeof credentialId !== 'string' ||
        !ALLOWED_CREDENTIALS.has(credentialId) ||
        typeof secret !== 'string' ||
        secret.length === 0 ||
        secret.length > 10_000
      ) {
        return { ok: false, error: 'invalid_id' }
      }
      if (!safeStorage.isEncryptionAvailable()) {
        return { ok: false, error: 'secure_storage_unavailable' }
      }

      try {
        const file = await readCredentials()
        file.credentials[credentialId] = safeStorage
          .encryptString(secret)
          .toString('base64')
        await writeCredentials(file)
        publishCredentialChange()
        return { ok: true }
      } catch {
        return { ok: false, error: 'storage_error' }
      }
    }
  )

  ipcMain.handle(
    'credentials:has',
    async (_event, credentialId: unknown): Promise<boolean> => {
      if (typeof credentialId !== 'string' || !ALLOWED_CREDENTIALS.has(credentialId))
        return false
      return hasEffectiveCredential(credentialId)
    }
  )

  ipcMain.handle(
    'credentials:remove',
    async (_event, credentialId: unknown): Promise<CredentialResult> => {
      if (typeof credentialId !== 'string' || !ALLOWED_CREDENTIALS.has(credentialId)) {
        return { ok: false, error: 'invalid_id' }
      }
      try {
        const file = await readCredentials()
        delete file.credentials[credentialId]
        await writeCredentials(file)
        publishCredentialChange()
        return { ok: true }
      } catch {
        return { ok: false, error: 'storage_error' }
      }
    }
  )
}

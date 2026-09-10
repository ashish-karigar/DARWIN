import { app, ipcMain, safeStorage } from 'electron'
import { readFile, rename, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

const ALLOWED_CREDENTIALS = new Set([
  'groq.apiKey',
  'fishAudio.apiKey',
  'spotify.clientId',
  'spotify.clientSecret'
])

interface CredentialFile {
  version: 1
  credentials: Record<string, string>
}

export interface CredentialResult {
  ok: boolean
  error?: 'invalid_id' | 'secure_storage_unavailable' | 'storage_error'
}

const credentialPath = () => join(app.getPath('userData'), 'darwin-credentials.json')

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
      const file = await readCredentials()
      return Boolean(file.credentials[credentialId])
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
        return { ok: true }
      } catch {
        return { ok: false, error: 'storage_error' }
      }
    }
  )
}

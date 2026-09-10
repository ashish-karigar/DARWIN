import type { AppManifest } from '../../shared/contracts'
import { appManifestSchema } from '../../shared/contracts'
import assistantManifest from '../../apps/assistant/manifest.json'
import settingsManifest from '../../apps/settings/manifest.json'
import youtubeManifest from '../../apps/youtube/manifest.json'
import remindersManifest from '../../apps/reminders/manifest.json'
import cameraManifest from '../../apps/camera/manifest.json'

export interface AppRegistryIssue {
  index: number
  appId: string | null
  code: 'invalid_manifest' | 'duplicate_id'
  message: string
}

export interface AppRegistryResult {
  apps: readonly AppManifest[]
  issues: readonly AppRegistryIssue[]
}

const readCandidateId = (candidate: unknown): string | null => {
  if (typeof candidate !== 'object' || candidate === null || !('id' in candidate))
    return null
  return typeof candidate.id === 'string' ? candidate.id : null
}

const validationMessage = (error: {
  issues: { path: PropertyKey[]; message: string }[]
}) =>
  error.issues
    .map(
      (issue) =>
        `${issue.path.length ? issue.path.join('.') : 'manifest'}: ${issue.message}`
    )
    .join('; ')

export class AppRegistry {
  readonly issues: readonly AppRegistryIssue[]
  readonly #apps: readonly AppManifest[]
  readonly #byId: ReadonlyMap<string, AppManifest>

  constructor(candidates: readonly unknown[]) {
    const apps: AppManifest[] = []
    const issues: AppRegistryIssue[] = []
    const ids = new Set<string>()

    candidates.forEach((candidate, index) => {
      const result = appManifestSchema.safeParse(candidate)
      if (!result.success) {
        issues.push({
          index,
          appId: readCandidateId(candidate),
          code: 'invalid_manifest',
          message: validationMessage(result.error)
        })
        return
      }

      if (ids.has(result.data.id)) {
        issues.push({
          index,
          appId: result.data.id,
          code: 'duplicate_id',
          message: `Duplicate application ID: ${result.data.id}`
        })
        return
      }

      ids.add(result.data.id)
      apps.push(Object.freeze(result.data))
    })

    apps.sort(
      (left, right) =>
        left.launcherOrder - right.launcherOrder || left.name.localeCompare(right.name)
    )
    this.#apps = Object.freeze(apps)
    this.#byId = new Map(apps.map((app) => [app.id, app]))
    this.issues = Object.freeze(issues)
  }

  list(): readonly AppManifest[] {
    return this.#apps
  }

  get(appId: string): AppManifest | undefined {
    return this.#byId.get(appId)
  }

  has(appId: string): boolean {
    return this.#byId.has(appId)
  }

  result(): AppRegistryResult {
    return { apps: this.#apps, issues: this.issues }
  }
}

const bundledManifests: readonly unknown[] = [
  assistantManifest,
  settingsManifest,
  remindersManifest,
  cameraManifest,
  youtubeManifest
]

export const appRegistry = new AppRegistry(bundledManifests)

if (appRegistry.issues.length > 0) {
  console.error('Some DARWIN applications were skipped.', appRegistry.issues)
}

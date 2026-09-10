import { describe, expect, it } from 'vitest'
import { AppRegistry, appRegistry } from './registry'

const validApp = {
  id: 'darwin.test',
  name: 'Test',
  description: 'Test application',
  version: '1.0.0',
  type: 'native',
  entry: 'test'
}

describe('AppRegistry', () => {
  it('loads bundled manifests in launcher order', () => {
    expect(appRegistry.list().map((app) => app.id)).toEqual([
      'darwin.assistant',
      'darwin.reminders',
      'darwin.settings',
      'darwin.camera',
      'darwin.youtube'
    ])
    expect(appRegistry.issues).toEqual([])
  })

  it('supports lookup without exposing mutable catalog state', () => {
    expect(appRegistry.get('darwin.settings')?.name).toBe('Settings')
    expect(appRegistry.has('darwin.missing')).toBe(false)
    expect(Object.isFrozen(appRegistry.list())).toBe(true)
  })

  it('skips invalid manifests with actionable diagnostics', () => {
    const registry = new AppRegistry([validApp, { id: 'BAD ID', type: 'web' }])
    expect(registry.list()).toHaveLength(1)
    expect(registry.issues).toEqual([
      expect.objectContaining({
        appId: 'BAD ID',
        code: 'invalid_manifest',
        message: expect.stringContaining('id:')
      })
    ])
  })

  it('keeps the first app when IDs are duplicated', () => {
    const registry = new AppRegistry([validApp, { ...validApp, name: 'Duplicate' }])
    expect(registry.list()).toHaveLength(1)
    expect(registry.get('darwin.test')?.name).toBe('Test')
    expect(registry.issues[0]).toMatchObject({
      code: 'duplicate_id',
      appId: 'darwin.test'
    })
  })

  it('sorts by launcher order and then name', () => {
    const registry = new AppRegistry([
      { ...validApp, id: 'darwin.z', name: 'Zulu', launcherOrder: 20 },
      { ...validApp, id: 'darwin.b', name: 'Beta', launcherOrder: 10 },
      { ...validApp, id: 'darwin.a', name: 'Alpha', launcherOrder: 10 }
    ])
    expect(registry.list().map((app) => app.name)).toEqual(['Alpha', 'Beta', 'Zulu'])
  })
})

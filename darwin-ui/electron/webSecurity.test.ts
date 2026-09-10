import { describe, expect, it } from 'vitest'
import {
  isAllowedWebUrl,
  validateWebAppRequest,
  webAppUpdateSchema
} from './webSecurity.js'

const valid = {
  instanceId: '11111111-1111-4111-8111-111111111111',
  appId: 'darwin.youtube',
  url: 'https://www.youtube.com/',
  allowedOrigins: ['https://www.youtube.com'],
  permissions: ['media.fullscreen'],
  session: 'darwin.youtube',
  bounds: { x: 10, y: 80, width: 700, height: 400 }
}

describe('web app IPC validation', () => {
  it('accepts a valid request and same-origin paths', () => {
    expect(validateWebAppRequest(valid).appId).toBe('darwin.youtube')
    expect(
      isAllowedWebUrl('https://www.youtube.com/watch?v=1', valid.allowedOrigins)
    ).toBe(true)
  })

  it('rejects unapproved origins and non-HTTPS URLs', () => {
    expect(() =>
      validateWebAppRequest({ ...valid, url: 'https://evil.example' })
    ).toThrow()
    expect(isAllowedWebUrl('http://www.youtube.com', valid.allowedOrigins)).toBe(false)
    expect(isAllowedWebUrl('javascript:alert(1)', valid.allowedOrigins)).toBe(false)
  })

  it('rejects malformed bounds and instance identifiers', () => {
    expect(
      webAppUpdateSchema.safeParse({
        instanceId: 'bad',
        bounds: valid.bounds,
        visible: true,
        focused: false
      }).success
    ).toBe(false)
    expect(
      webAppUpdateSchema.safeParse({
        instanceId: valid.instanceId,
        bounds: { ...valid.bounds, width: -1 },
        visible: true,
        focused: false
      }).success
    ).toBe(false)
  })
})

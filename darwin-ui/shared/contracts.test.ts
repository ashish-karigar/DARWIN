import { describe, expect, it } from 'vitest'
import {
  PROTOCOL_VERSION,
  UnsupportedProtocolVersionError,
  appManifestSchema,
  darwinInputEventSchema,
  parseClientMessage,
  windowStateSchema
} from './contracts'

const messageBase = {
  protocolVersion: PROTOCOL_VERSION,
  messageId: '6f6bbfd0-dde9-4c27-9234-7f8156631d7a',
  timestamp: '2026-09-10T02:00:00Z'
}

describe('app contracts', () => {
  it('accepts a valid native app manifest', () => {
    const manifest = appManifestSchema.parse({
      id: 'darwin.settings',
      name: 'Settings',
      version: '1.0.0',
      type: 'native',
      entry: 'settings'
    })

    expect(manifest.instancePolicy).toBe('single')
  })

  it('rejects a web app without a URL', () => {
    expect(() =>
      appManifestSchema.parse({
        id: 'darwin.video',
        name: 'Video',
        version: '1.0.0',
        type: 'web'
      })
    ).toThrow()
  })

  it('rejects a web app whose URL is outside its approved HTTPS origins', () => {
    expect(() =>
      appManifestSchema.parse({
        id: 'darwin.video',
        name: 'Video',
        version: '1.0.0',
        type: 'web',
        url: 'https://video.example',
        allowedOrigins: ['https://evil.example'],
        session: 'darwin.video'
      })
    ).toThrow()
  })

  it('rejects unreachable window dimensions', () => {
    expect(() =>
      windowStateSchema.parse({
        instanceId: '86e30dbf-7e67-42bb-b046-5fa4959065a5',
        bounds: { x: 0, y: 0, width: 0, height: 600 },
        mode: 'normal',
        focused: true,
        zIndex: 1
      })
    ).toThrow()
  })
})

describe('input contracts', () => {
  it('accepts a normalized pointer event', () => {
    const event = darwinInputEventSchema.parse({
      type: 'pointer.move',
      source: 'gesture',
      timestamp: 1_789_000_000_000,
      confidence: 0.95,
      x: 320,
      y: 180
    })

    expect(event.type).toBe('pointer.move')
  })

  it('rejects confidence outside the normalized range', () => {
    expect(() =>
      darwinInputEventSchema.parse({
        type: 'pointer.move',
        source: 'gesture',
        timestamp: 1_789_000_000_000,
        confidence: 1.5,
        x: 320,
        y: 180
      })
    ).toThrow()
  })
})

describe('wire protocol', () => {
  it('accepts a versioned assistant request', () => {
    const message = parseClientMessage({
      ...messageBase,
      type: 'assistant.request',
      sessionId: 'default',
      content: 'Status report.'
    })

    expect(message.type).toBe('assistant.request')
  })

  it('rejects malformed messages', () => {
    expect(() =>
      parseClientMessage({
        ...messageBase,
        type: 'assistant.request',
        sessionId: 'default',
        content: ''
      })
    ).toThrow()
  })

  it('reports unsupported protocol versions explicitly', () => {
    expect(() =>
      parseClientMessage({
        ...messageBase,
        protocolVersion: '2.0',
        type: 'assistant.request',
        sessionId: 'default',
        content: 'Status report.'
      })
    ).toThrow(UnsupportedProtocolVersionError)
  })
})

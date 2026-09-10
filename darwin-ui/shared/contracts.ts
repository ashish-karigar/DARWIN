import { z } from 'zod'

export const PROTOCOL_VERSION = '1.0' as const

const identifierSchema = z
  .string()
  .min(1)
  .max(128)
  .regex(/^[a-z0-9]+(?:[._-][a-z0-9]+)*$/)

export const windowBoundsSchema = z.object({
  x: z.number().finite(),
  y: z.number().finite(),
  width: z.number().finite().positive(),
  height: z.number().finite().positive()
})

export type WindowBounds = z.infer<typeof windowBoundsSchema>

export const windowStateSchema = z.object({
  instanceId: z.string().uuid(),
  bounds: windowBoundsSchema,
  restoreBounds: windowBoundsSchema.nullable().default(null),
  mode: z.enum(['normal', 'minimized', 'maximized']),
  focused: z.boolean(),
  zIndex: z.number().int().nonnegative()
})

export type WindowState = z.infer<typeof windowStateSchema>

export const appManifestSchema = z
  .object({
    id: identifierSchema,
    name: z.string().trim().min(1).max(80),
    description: z.string().trim().max(160).default(''),
    version: z.string().trim().min(1).max(32),
    type: z.enum(['native', 'web', 'external']),
    icon: z.string().trim().min(1).optional(),
    entry: z.string().trim().min(1).optional(),
    url: z.url().optional(),
    allowedOrigins: z.array(z.url()).max(32).default([]),
    permissions: z.array(identifierSchema).max(64).default([]),
    session: identifierSchema.optional(),
    instancePolicy: z.enum(['single', 'multiple']).default('single'),
    pinned: z.boolean().default(false),
    launcherOrder: z.number().int().nonnegative().default(100),
    displayMode: z.enum(['window', 'fullscreen']).default('window'),
    windowStyle: z.enum(['frameless', 'document']).default('frameless'),
    edgeEffect: z.enum(['flow', 'none']).default('flow')
  })
  .superRefine((manifest, context) => {
    if (manifest.type === 'native' && !manifest.entry) {
      context.addIssue({
        code: 'custom',
        path: ['entry'],
        message: 'Native apps require an entry.'
      })
    }

    if (manifest.type === 'web' && !manifest.url) {
      context.addIssue({
        code: 'custom',
        path: ['url'],
        message: 'Web apps require a URL.'
      })
    }
    if (manifest.type === 'web' && !manifest.session) {
      context.addIssue({
        code: 'custom',
        path: ['session'],
        message: 'Web apps require an isolated session.'
      })
    }
    if (manifest.type === 'web' && manifest.allowedOrigins.length === 0) {
      context.addIssue({
        code: 'custom',
        path: ['allowedOrigins'],
        message: 'Web apps require at least one approved origin.'
      })
    }
    if (manifest.type === 'web' && manifest.url) {
      const initial = new URL(manifest.url)
      const approved = manifest.allowedOrigins.some((value) => {
        const allowed = new URL(value)
        return allowed.protocol === 'https:' && allowed.origin === initial.origin
      })
      if (initial.protocol !== 'https:' || !approved) {
        context.addIssue({
          code: 'custom',
          path: ['url'],
          message: 'Web app URL must use an approved HTTPS origin.'
        })
      }
    }
  })

export type AppManifest = z.infer<typeof appManifestSchema>

export const appInstanceSchema = z.object({
  id: z.string().uuid(),
  appId: identifierSchema,
  launchedAt: z.iso.datetime(),
  status: z.enum(['launching', 'running', 'suspended', 'error', 'closed']),
  windowId: z.string().uuid().nullable(),
  error: z.string().max(500).nullable().default(null)
})

export type AppInstance = z.infer<typeof appInstanceSchema>

const inputMetadataSchema = z.object({
  source: z.enum([
    'mouse',
    'keyboard',
    'voice',
    'gesture',
    'gamepad',
    'remote',
    'system'
  ]),
  timestamp: z.number().int().nonnegative(),
  confidence: z.number().min(0).max(1).optional()
})

export const darwinInputEventSchema = z.discriminatedUnion('type', [
  inputMetadataSchema.extend({
    type: z.literal('pointer.move'),
    x: z.number().finite(),
    y: z.number().finite()
  }),
  inputMetadataSchema.extend({
    type: z.literal('pointer.click'),
    button: z.enum(['left', 'middle', 'right']),
    action: z.enum(['down', 'up', 'click'])
  }),
  inputMetadataSchema.extend({
    type: z.literal('navigation'),
    action: z.enum(['back', 'forward', 'home', 'select', 'cancel', 'next', 'previous'])
  }),
  inputMetadataSchema.extend({
    type: z.literal('text'),
    text: z.string().max(10_000)
  }),
  inputMetadataSchema.extend({
    type: z.literal('media'),
    action: z.enum(['play', 'pause', 'toggle', 'stop', 'seek-forward', 'seek-backward'])
  }),
  inputMetadataSchema.extend({
    type: z.literal('command'),
    command: z.string().trim().min(1).max(2_000)
  })
])

export type DarwinInputEvent = z.infer<typeof darwinInputEventSchema>

const messageBase = {
  protocolVersion: z.string(),
  messageId: z.string().uuid(),
  timestamp: z.iso.datetime()
}

export const clientMessageSchema = z.discriminatedUnion('type', [
  z.object({
    ...messageBase,
    type: z.literal('session.hello'),
    clientName: z.string().trim().min(1).max(80)
  }),
  z.object({
    ...messageBase,
    type: z.literal('assistant.request'),
    sessionId: identifierSchema,
    content: z.string().trim().min(1).max(50_000)
  }),
  z.object({
    ...messageBase,
    type: z.literal('assistant.cancel'),
    requestId: z.string().uuid()
  }),
  z.object({
    ...messageBase,
    type: z.literal('confirmation.response'),
    requestId: z.string().uuid(),
    approved: z.boolean()
  })
])

export type ClientMessage = z.infer<typeof clientMessageSchema>

export const serverMessageSchema = z.discriminatedUnion('type', [
  z.object({
    ...messageBase,
    type: z.literal('session.ready'),
    backendVersion: z.string(),
    acceptedProtocolVersion: z.string()
  }),
  z.object({
    ...messageBase,
    type: z.literal('assistant.state'),
    requestId: z.string().uuid().nullable(),
    state: z.enum(['idle', 'listening', 'transcribing', 'thinking', 'speaking', 'error'])
  }),
  z.object({
    ...messageBase,
    type: z.literal('assistant.response'),
    requestId: z.string().uuid(),
    content: z.string().max(100_000),
    final: z.boolean()
  }),
  z.object({
    ...messageBase,
    type: z.literal('confirmation.required'),
    requestId: z.string().uuid(),
    summary: z.string().trim().min(1).max(1_000),
    risk: z.enum(['low', 'reversible_write', 'destructive', 'sensitive']),
    expiresAt: z.iso.datetime()
  }),
  z.object({
    ...messageBase,
    type: z.literal('error'),
    requestId: z.string().uuid().nullable(),
    code: z.string().trim().min(1).max(80),
    message: z.string().trim().min(1).max(1_000),
    recoverable: z.boolean(),
    details: z.record(z.string(), z.unknown()).optional()
  })
])

export type ServerMessage = z.infer<typeof serverMessageSchema>

export const parseClientMessage = (value: unknown): ClientMessage => {
  const message = clientMessageSchema.parse(value)
  assertSupportedProtocolVersion(message.protocolVersion)
  return message
}

export const parseServerMessage = (value: unknown): ServerMessage => {
  const message = serverMessageSchema.parse(value)
  assertSupportedProtocolVersion(message.protocolVersion)
  return message
}

export class UnsupportedProtocolVersionError extends Error {
  readonly receivedVersion: string
  readonly supportedVersion = PROTOCOL_VERSION

  constructor(receivedVersion: string) {
    super(
      `Unsupported protocol version: ${receivedVersion}. Expected ${PROTOCOL_VERSION}.`
    )
    this.name = 'UnsupportedProtocolVersionError'
    this.receivedVersion = receivedVersion
  }
}

export const assertSupportedProtocolVersion = (version: string): void => {
  if (version !== PROTOCOL_VERSION) {
    throw new UnsupportedProtocolVersionError(version)
  }
}

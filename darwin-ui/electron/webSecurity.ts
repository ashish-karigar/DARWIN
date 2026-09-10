import { z } from 'zod'

const id = z.string().uuid()
export const webAppCreateSchema = z.object({
  instanceId: id,
  appId: z.string().regex(/^[a-z0-9]+(?:[._-][a-z0-9]+)*$/),
  url: z.url(),
  allowedOrigins: z.array(z.url()).min(1).max(32),
  permissions: z.array(z.string()).max(64).default([]),
  session: z.string().regex(/^[a-z0-9]+(?:[._-][a-z0-9]+)*$/),
  bounds: z.object({
    x: z.number().int(),
    y: z.number().int(),
    width: z.number().int().positive(),
    height: z.number().int().positive()
  }),
  edgeEffect: z.enum(['flow', 'none']).default('flow')
})

export const webAppUpdateSchema = z.object({
  instanceId: id,
  bounds: webAppCreateSchema.shape.bounds,
  visible: z.boolean(),
  keepAlive: z.boolean().default(false),
  focused: z.boolean(),
  overlayColor: z.enum(['#000000', '#0c0c0d'])
})

export const webAppIdSchema = id
export const webAppNavigationSchema = z.object({
  instanceId: id,
  action: z.enum(['back', 'forward', 'reload'])
})
export type WebAppCreateRequest = z.infer<typeof webAppCreateSchema>
export type WebAppUpdateRequest = z.infer<typeof webAppUpdateSchema>

export const normalizedOrigin = (value: string): string | null => {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' ? url.origin : null
  } catch {
    return null
  }
}

export const isAllowedWebUrl = (value: string, origins: readonly string[]) => {
  const origin = normalizedOrigin(value)
  return (
    origin !== null && origins.some((allowed) => normalizedOrigin(allowed) === origin)
  )
}

export const validateWebAppRequest = (value: unknown): WebAppCreateRequest => {
  const request = webAppCreateSchema.parse(value)
  if (!isAllowedWebUrl(request.url, request.allowedOrigins)) {
    throw new Error('Initial URL is outside the approved origins.')
  }
  return request
}

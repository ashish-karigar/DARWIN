import { useEffect, useState } from 'react'
import { z } from 'zod'

const statsSchema = z.object({
  cpu: z.number().min(0).max(100),
  battery: z.number().min(0).max(100).nullable()
})

const usageSchema = z.object({
  available: z.literal(true),
  used_tokens: z.number().int().nonnegative(),
  daily_limit_tokens: z.number().int().positive(),
  remaining_tokens: z.number().int().nonnegative(),
  request_count: z.number().int().nonnegative(),
  reset_at: z.string(),
  tracked_since: z.string().nullable(),
  scope: z.literal('darwin-local')
})

type GroqUsage = z.infer<typeof usageSchema>

export function SystemStats() {
  const [stats, setStats] = useState({ cpu: 0, battery: null as number | null })
  const [usage, setUsage] = useState<GroqUsage | null>(null)

  useEffect(() => {
    const bridge = window.darwinSystemStats
    if (!bridge) return
    bridge.subscribe((value) => {
      const parsed = statsSchema.safeParse(value)
      if (parsed.success) setStats(parsed.data)
    })
    return () => bridge.unsubscribe()
  }, [])

  useEffect(() => {
    const bridge = window.darwinAssistantSession
    if (!bridge?.getUsage) return

    let active = true
    const refresh = async () => {
      const parsed = usageSchema.safeParse(await bridge.getUsage())
      if (active) setUsage(parsed.success ? parsed.data : null)
    }

    void refresh()
    const timer = window.setInterval(() => void refresh(), 5_000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  const usageTitle = usage
    ? `${usage.used_tokens.toLocaleString()} Groq tokens tracked by DARWIN today; ${usage.remaining_tokens.toLocaleString()} remaining before the configured daily limit. Groq usage from other projects or API keys is not included.`
    : 'Groq usage is unavailable until the assistant backend connects.'

  return (
    <aside className="system-stats" aria-label="Computer performance">
      <span><small>CPU</small>{stats.cpu}%</span>
      <span title={usageTitle}>
        <small>GROQ TODAY</small>
        {usage
          ? `${usage.used_tokens.toLocaleString()} / ${usage.daily_limit_tokens.toLocaleString()}`
          : '— / 200,000'}
      </span>
      <span><small>BATTERY</small>{stats.battery === null ? '—' : `${stats.battery}%`}</span>
    </aside>
  )
}

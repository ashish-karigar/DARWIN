import { useEffect, useRef } from 'react'
import { useSettingsStore } from '../stores/settingsStore'

const count = 96
const points = Array.from({ length: count }, (_, index) => {
  const y = 1 - (index / (count - 1)) * 2
  const radius = Math.sqrt(1 - y * y)
  const angle = index * Math.PI * (3 - Math.sqrt(5))
  return { x: Math.cos(angle) * radius, y, z: Math.sin(angle) * radius, zone: index % 6 }
})
const links = points.flatMap((point, index) =>
  points
    .map((candidate, target) => ({
      target,
      distance: Math.hypot(
        point.x - candidate.x,
        point.y - candidate.y,
        point.z - candidate.z
      )
    }))
    .filter(({ target }) => target !== index)
    .sort((a, b) => a.distance - b.distance)
    .slice(0, 2)
    .map(({ target }) => [index, target] as const)
)
export function NeuralCore() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const pointerRef = useRef<{ x: number; y: number } | null>(null)
  const thicknessRef = useRef(1)
  const brightness = useSettingsStore((state) => state.neuralBrightness)
  const thickness = useSettingsStore((state) => state.neuralThickness)
  const warmth = useSettingsStore((state) => state.neuralWarmth)
  useEffect(() => {
    thicknessRef.current = thickness
  }, [thickness])
  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    let frame = 0
    let activeZone = -1
    let activeUntil = 0
    const activate = (event?: Event) => {
      activeZone =
        (event as CustomEvent<{ zone?: number }> | undefined)?.detail?.zone ??
        Math.floor(Math.random() * 6)
      activeUntil = performance.now() + 2400
    }
    window.addEventListener('darwin:activity', activate)
    const draw = (now: number) => {
      const ratio = window.devicePixelRatio || 1
      const rect = canvas.getBoundingClientRect()
      if (canvas.width !== rect.width * ratio || canvas.height !== rect.height * ratio) {
        canvas.width = rect.width * ratio
        canvas.height = rect.height * ratio
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      context.clearRect(0, 0, rect.width, rect.height)
      const size = Math.min(rect.width, rect.height) * 0.48
      const cx = rect.width / 2
      const cy = rect.height / 2
      const rotation = now * 0.00008
      const ambient = context.createRadialGradient(
        cx,
        cy,
        size * 0.08,
        cx,
        cy,
        size * 0.78
      )
      ambient.addColorStop(0, 'rgba(216,164,82,.07)')
      ambient.addColorStop(0.55, 'rgba(183,130,54,.03)')
      ambient.addColorStop(1, 'rgba(12,12,13,0)')
      context.fillStyle = ambient
      context.fillRect(cx - size, cy - size, size * 2, size * 2)
      const projected = points.map((point) => {
        const x = point.x * Math.cos(rotation) - point.z * Math.sin(rotation)
        const z = point.x * Math.sin(rotation) + point.z * Math.cos(rotation)
        const scale = 1 / (1.9 - z * 0.42)
        return {
          x: cx + x * size * scale,
          y: cy + point.y * size * scale,
          z,
          scale,
          zone: point.zone
        }
      })
      const hoverRadius = size * 0.28
      const glowAt = (point: { x: number; y: number }) => {
        const pointer = pointerRef.current
        if (!pointer) return 0
        const distance = Math.hypot(point.x - pointer.x, point.y - pointer.y)
        if (distance >= hoverRadius) return 0
        const normalized = 1 - distance / hoverRadius
        return normalized * normalized
      }
      for (const [a, b] of links) {
        const from = projected[a]!
        const to = projected[b]!
        const activity =
          now < activeUntil && (from.zone === activeZone || to.zone === activeZone)
            ? 0.22
            : 0
        const glow = Math.max(glowAt(from), glowAt(to), activity)
        context.beginPath()
        context.moveTo(from.x, from.y)
        context.lineTo(to.x, to.y)
        context.strokeStyle =
          glow > 0
            ? `rgba(244,176,65,${0.1 + glow * 0.24})`
            : `rgba(211,166,91,${0.085 + Math.max(0, from.z) * 0.085})`
        context.lineWidth = (0.6 + glow * 0.35) * thicknessRef.current
        context.shadowColor = glow > 0 ? 'rgba(255,166,45,.52)' : 'transparent'
        context.shadowBlur = glow * 10
        context.stroke()
      }
      projected
        .sort((a, b) => a.z - b.z)
        .forEach((point) => {
          const activity = now < activeUntil && point.zone === activeZone ? 0.22 : 0
          const glow = Math.max(glowAt(point), activity)
          context.beginPath()
          context.arc(point.x, point.y, (1.4 + glow * 0.8) * point.scale, 0, Math.PI * 2)
          context.fillStyle =
            glow > 0
              ? `rgba(255,190,76,${0.42 + glow * 0.38})`
              : `rgba(224,180,104,${0.22 + (point.z + 1) * 0.14})`
          context.shadowColor = glow > 0 ? 'rgba(255,158,32,.58)' : 'transparent'
          context.shadowBlur = glow * 11
          context.fill()
        })
      context.shadowBlur = 0
      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('darwin:activity', activate)
    }
  }, [])
  return (
    <canvas
      ref={canvasRef}
      className="neural-core"
      style={{
        filter: `brightness(${1 + (brightness - 1) * 0.18}) sepia(${warmth / 10}) saturate(${1 + warmth * 0.42}) contrast(1.15)`
      }}
      aria-label="DARWIN neural core"
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect()
        pointerRef.current = {
          x: event.clientX - rect.left,
          y: event.clientY - rect.top
        }
      }}
      onPointerLeave={() => {
        pointerRef.current = null
      }}
    />
  )
}

import { useEffect, useRef } from 'react'
import { useSettingsStore } from '../stores/settingsStore'
import { useAssistantStore, type AssistantState } from '../stores/assistantStore'

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
  const assistantStateRef = useRef<AssistantState>('idle')
  const microphoneLevelRef = useRef(0)
  const assistantState = useAssistantStore((state) => state.state)
  const brightness = useSettingsStore((state) => state.neuralBrightness)
  const thickness = useSettingsStore((state) => state.neuralThickness)
  const warmth = useSettingsStore((state) => state.neuralWarmth)
  const voiceEnabled = useSettingsStore((state) => state.voiceEnabled)
  useEffect(() => {
    thicknessRef.current = thickness
  }, [thickness])
  useEffect(() => {
    assistantStateRef.current = assistantState
  }, [assistantState])
  useEffect(() => {
    if (!voiceEnabled || !navigator.mediaDevices?.getUserMedia) {
      microphoneLevelRef.current = 0
      return
    }
    let disposed = false
    let stream: MediaStream | null = null
    let audioContext: AudioContext | null = null
    let microphoneFrame = 0
    void navigator.mediaDevices
      .getUserMedia({
        audio: {
          autoGainControl: true,
          echoCancellation: true,
          noiseSuppression: true
        },
        video: false
      })
      .then((mediaStream) => {
        if (disposed) {
          mediaStream.getTracks().forEach((track) => track.stop())
          return
        }
        stream = mediaStream
        audioContext = new AudioContext({ latencyHint: 'interactive' })
        const source = audioContext.createMediaStreamSource(mediaStream)
        const analyser = audioContext.createAnalyser()
        analyser.fftSize = 512
        analyser.smoothingTimeConstant = 0
        source.connect(analyser)
        const samples = new Float32Array(analyser.fftSize)
        let noiseFloor = 0.008
        let smoothedRms = 0
        let envelope = 0
        const measure = () => {
          analyser.getFloatTimeDomainData(samples)
          let energy = 0
          for (const sample of samples) energy += sample * sample
          const rms = Math.sqrt(energy / samples.length)
          smoothedRms += (rms - smoothedRms) * 0.16
          if (smoothedRms < noiseFloor * 1.7)
            noiseFloor = noiseFloor * 0.99 + smoothedRms * 0.01
          const threshold = Math.max(0.012, noiseFloor * 2.15)
          const detected = Math.max(0, Math.min(1, (smoothedRms - threshold) / 0.095))
          const smoothing = detected > envelope ? 0.22 : 0.055
          envelope += (detected - envelope) * smoothing
          microphoneLevelRef.current = envelope
          microphoneFrame = requestAnimationFrame(measure)
        }
        microphoneFrame = requestAnimationFrame(measure)
      })
      .catch(() => {
        microphoneLevelRef.current = 0
      })
    return () => {
      disposed = true
      cancelAnimationFrame(microphoneFrame)
      microphoneLevelRef.current = 0
      stream?.getTracks().forEach((track) => track.stop())
      if (audioContext) void audioContext.close()
    }
  }, [voiceEnabled])
  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    let frame = 0
    let activeZone = -1
    let activeUntil = 0
    let smoothedAudioLevel = 0
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
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
      const state = assistantStateRef.current
      const voiceWave =
        state === 'speaking' && !reduceMotion
          ? Math.sin(now * 0.009) * 0.52 +
            Math.sin(now * 0.015 + 1.1) * 0.3 +
            Math.sin(now * 0.023 + 0.4) * 0.18
          : 0
      const speechScale = state === 'speaking' ? 1.04 + voiceWave * 0.07 : 1
      const stateGlow = state === 'speaking' ? 0.2 + Math.max(0, voiceWave) * 0.08 : 0
      const size = Math.min(rect.width, rect.height) * 0.48 * speechScale
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
      ambient.addColorStop(0, `rgba(232,183,101,${0.07 + stateGlow * 0.32})`)
      ambient.addColorStop(0.55, `rgba(195,143,65,${0.03 + stateGlow * 0.15})`)
      ambient.addColorStop(1, 'rgba(12,12,13,0)')
      context.fillStyle = ambient
      context.fillRect(cx - size, cy - size, size * 2, size * 2)
      const targetAudioLevel = microphoneLevelRef.current
      const audioSmoothing = targetAudioLevel > smoothedAudioLevel ? 0.16 : 0.055
      smoothedAudioLevel += (targetAudioLevel - smoothedAudioLevel) * audioSmoothing
      if (state === 'listening' || smoothedAudioLevel > 0.005) {
        const innerRadius = size * (0.115 + smoothedAudioLevel * 0.07)
        const innerGlow = context.createRadialGradient(
          cx,
          cy,
          0,
          cx,
          cy,
          innerRadius * 2.4
        )
        innerGlow.addColorStop(0, `rgba(255,207,123,${smoothedAudioLevel * 0.92})`)
        innerGlow.addColorStop(0.38, `rgba(225,160,62,${smoothedAudioLevel * 0.58})`)
        innerGlow.addColorStop(1, 'rgba(171,105,32,0)')
        context.fillStyle = innerGlow
        context.beginPath()
        context.arc(cx, cy, innerRadius * 2.4, 0, Math.PI * 2)
        context.fill()
      }
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
        const glow = Math.max(glowAt(from), glowAt(to), activity, stateGlow)
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
          const glow = Math.max(glowAt(point), activity, stateGlow)
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
      data-assistant-state={assistantState}
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

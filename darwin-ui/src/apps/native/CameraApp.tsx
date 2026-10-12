import { useCallback, useEffect, useRef, useState } from 'react'
import { useNativeApp } from './NativeAppContext'

type CameraState = 'starting' | 'ready' | 'denied' | 'unavailable' | 'error'
type DetectionState = 'off' | 'loading' | 'active' | 'error'
type Detection = {
  label: string
  confidence: number
  x: number
  y: number
  width: number
  height: number
}

export function CameraApp() {
  const { window: appWindow } = useNativeApp()
  const videoRef = useRef<HTMLVideoElement>(null)
  const detectionCanvasRef = useRef<HTMLCanvasElement>(null)
  const sampleCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [state, setState] = useState<CameraState>('starting')
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState('')
  const [mirrored, setMirrored] = useState(true)
  const [detectionState, setDetectionState] = useState<DetectionState>('off')
  const [detections, setDetections] = useState<Detection[]>([])
  const [detectionError, setDetectionError] = useState('')

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
  }, [])

  const start = useCallback(
    async (selectedDevice = '') => {
      stop()
      setDetections([])
      setState('starting')
      if (!navigator.mediaDevices?.getUserMedia) {
        setState('unavailable')
        return
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: selectedDevice
            ? { deviceId: { exact: selectedDevice } }
            : { facingMode: 'user', width: { ideal: 1920 }, height: { ideal: 1080 } }
        })
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play()
        }
        const cameras = (await navigator.mediaDevices.enumerateDevices()).filter(
          (device) => device.kind === 'videoinput'
        )
        setDevices(cameras)
        setDeviceId(stream.getVideoTracks()[0]?.getSettings().deviceId ?? selectedDevice)
        setState('ready')
      } catch (error) {
        setState(
          error instanceof DOMException &&
            (error.name === 'NotAllowedError' || error.name === 'SecurityError')
            ? 'denied'
            : error instanceof DOMException && error.name === 'NotFoundError'
              ? 'unavailable'
              : 'error'
        )
      }
    },
    [stop]
  )

  useEffect(() => {
    if (appWindow.mode === 'minimized') {
      stop()
      return
    }
    const timer = window.setTimeout(() => void start(deviceId), 0)
    return () => {
      window.clearTimeout(timer)
      stop()
    }
  }, [appWindow.mode, deviceId, start, stop])

  const drawDetections = useCallback(() => {
    const video = videoRef.current
    const canvas = detectionCanvasRef.current
    if (!video || !canvas) return
    const width = video.clientWidth
    const height = video.clientHeight
    const ratio = window.devicePixelRatio || 1
    canvas.width = Math.round(width * ratio)
    canvas.height = Math.round(height * ratio)
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`
    const context = canvas.getContext('2d')
    if (!context || !video.videoWidth || !video.videoHeight) return
    context.scale(ratio, ratio)
    context.clearRect(0, 0, width, height)

    const scale = Math.max(width / video.videoWidth, height / video.videoHeight)
    const renderedWidth = video.videoWidth * scale
    const renderedHeight = video.videoHeight * scale
    const offsetX = (width - renderedWidth) / 2
    const offsetY = (height - renderedHeight) / 2
    context.lineWidth = 1.5
    context.font = '500 11px system-ui, sans-serif'

    for (const detection of detections) {
      const rawX = mirrored ? 1 - detection.x - detection.width : detection.x
      const x = offsetX + rawX * renderedWidth
      const y = offsetY + detection.y * renderedHeight
      const boxWidth = detection.width * renderedWidth
      const boxHeight = detection.height * renderedHeight
      const label = `${detection.label} ${Math.round(detection.confidence * 100)}%`
      const labelWidth = context.measureText(label).width + 12
      const labelY = Math.max(0, y - 22)
      context.strokeStyle = 'rgba(232, 191, 111, .92)'
      context.fillStyle = 'rgba(8, 8, 8, .78)'
      context.strokeRect(x, y, boxWidth, boxHeight)
      context.fillRect(x, labelY, labelWidth, 20)
      context.fillStyle = 'rgba(244, 229, 198, .96)'
      context.fillText(label, x + 6, labelY + 14)
    }
  }, [detections, mirrored])

  useEffect(() => {
    drawDetections()
    const video = videoRef.current
    if (!video) return
    const observer = new ResizeObserver(drawDetections)
    observer.observe(video)
    return () => observer.disconnect()
  }, [drawDetections])

  useEffect(() => {
    if (
      detectionState === 'off' ||
      detectionState === 'error' ||
      state !== 'ready' ||
      appWindow.mode === 'minimized'
    ) {
      return
    }
    let cancelled = false
    let timer = 0
    const detectFrame = async () => {
      const video = videoRef.current
      if (cancelled || !video?.videoWidth || !window.darwinVision) return
      const sample = sampleCanvasRef.current ?? document.createElement('canvas')
      sampleCanvasRef.current = sample
      const width = Math.min(640, video.videoWidth)
      sample.width = width
      sample.height = Math.round((width * video.videoHeight) / video.videoWidth)
      const context = sample.getContext('2d', { alpha: false })
      if (!context) return
      context.drawImage(video, 0, 0, sample.width, sample.height)
      const image = sample.toDataURL('image/jpeg', 0.68).split(',', 2)[1]
      if (!image) return
      const result = await window.darwinVision.detect(image)
      if (cancelled) return
      if (result.ok) {
        setDetections(result.detections)
        setDetectionState('active')
        setDetectionError('')
        timer = window.setTimeout(() => void detectFrame(), 180)
      } else {
        setDetectionState('error')
        setDetectionError(
          result.code === 'dependencies_missing'
            ? 'Install the DARWIN vision package, then try again.'
            : result.error
        )
      }
    }
    void detectFrame()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [appWindow.mode, detectionState, state])

  const capture = useCallback(() => {
    const video = videoRef.current
    if (!video?.videoWidth) return
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const context = canvas.getContext('2d')
    if (!context) return
    if (mirrored) {
      context.translate(canvas.width, 0)
      context.scale(-1, 1)
    }
    context.drawImage(video, 0, 0)
    const link = document.createElement('a')
    link.download = `DARWIN-${new Date().toISOString().replaceAll(':', '-')}.jpg`
    link.href = canvas.toDataURL('image/jpeg', 0.94)
    link.click()
  }, [mirrored])

  useEffect(() => {
    const handleCommand = (event: Event) => {
      const action = (event as CustomEvent<{ action?: string }>).detail?.action
      if (action === 'close') appWindow.close()
      else if (action === 'capture') capture()
      else if (action === 'camera.next' || action === 'camera.previous') {
        if (devices.length < 2) return
        const currentIndex = Math.max(
          0,
          devices.findIndex((device) => device.deviceId === deviceId)
        )
        const direction = action === 'camera.next' ? 1 : -1
        const nextIndex = (currentIndex + direction + devices.length) % devices.length
        const nextDevice = devices[nextIndex]
        if (nextDevice) setDeviceId(nextDevice.deviceId)
      } else if (action === 'detection.start') {
        setDetectionError('')
        setDetectionState('loading')
      } else if (action === 'detection.stop') {
        setDetectionError('')
        setDetections([])
        setDetectionState('off')
      } else if (action === 'mirror.on') setMirrored(true)
      else if (action === 'mirror.off') setMirrored(false)
      else if (action === 'mirror.toggle') setMirrored((value) => !value)
    }
    window.addEventListener('darwin:camera-command', handleCommand)
    return () => window.removeEventListener('darwin:camera-command', handleCommand)
  }, [appWindow, capture, deviceId, devices])

  return (
    <main className="camera-app">
      <video
        ref={videoRef}
        className="camera-preview"
        data-mirrored={mirrored}
        playsInline
        muted
      />
      <canvas ref={detectionCanvasRef} className="camera-detections" aria-hidden="true" />
      {state !== 'ready' && (
        <div className="camera-state">
          <strong>
            {state === 'starting'
              ? 'Starting camera…'
              : state === 'denied'
                ? 'Camera access is off'
                : state === 'unavailable'
                  ? 'No camera found'
                  : 'Camera unavailable'}
          </strong>
          <p>
            {state === 'denied'
              ? 'Allow camera access for DARWIN in macOS Privacy & Security.'
              : 'Check the camera connection and try again.'}
          </p>
          {state !== 'starting' && (
            <button onClick={() => start(deviceId)}>Try again</button>
          )}
        </div>
      )}
      {state === 'ready' && (
        <>
          {detectionState === 'error' && (
            <div className="camera-detection-error" role="status">
              {detectionError}
            </div>
          )}
          <div className="camera-controls">
            {devices.length > 1 && (
              <select
                aria-label="Camera"
                value={deviceId}
                onChange={(event) => setDeviceId(event.target.value)}
              >
                {devices.map((device, index) => (
                  <option key={device.deviceId} value={device.deviceId}>
                    {device.label || `Camera ${index + 1}`}
                  </option>
                ))}
              </select>
            )}
            <button
              className="camera-mirror"
              type="button"
              data-active={mirrored}
              onClick={() => setMirrored((value) => !value)}
            >
              Mirror
            </button>
            <button
              className="camera-detect"
              type="button"
              data-active={detectionState === 'active' || detectionState === 'loading'}
              onClick={() => {
                if (detectionState === 'off' || detectionState === 'error') {
                  setDetectionState('loading')
                  setDetectionError('')
                } else {
                  setDetectionState('off')
                  setDetectionError('')
                  setDetections([])
                }
              }}
            >
              {detectionState === 'loading'
                ? 'Loading vision…'
                : detectionState === 'off'
                  ? 'Detect'
                  : detectionState === 'error'
                    ? 'Retry detection'
                    : `${detections.length} detected`}
            </button>
            <button
              className="camera-shutter"
              type="button"
              aria-label="Take photo"
              onClick={capture}
            >
              <i />
            </button>
          </div>
        </>
      )}
    </main>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { useNativeApp } from './NativeAppContext'

type CameraState = 'starting' | 'ready' | 'denied' | 'unavailable' | 'error'

export function CameraApp() {
  const { window: appWindow } = useNativeApp()
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [state, setState] = useState<CameraState>('starting')
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState('')
  const [mirrored, setMirrored] = useState(true)

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
  }, [])

  const start = useCallback(
    async (selectedDevice = '') => {
      stop()
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

  const capture = () => {
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
  }

  return (
    <main className="camera-app">
      <video
        ref={videoRef}
        className="camera-preview"
        data-mirrored={mirrored}
        playsInline
        muted
      />
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
            className="camera-shutter"
            type="button"
            aria-label="Take photo"
            onClick={capture}
          >
            <i />
          </button>
        </div>
      )}
    </main>
  )
}

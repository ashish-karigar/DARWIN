import { useNativeApp } from './NativeAppContext'

export function AssistantApp() {
  const { manifest } = useNativeApp()
  return (
    <div className="native-app-placeholder">
      <span className="native-app-placeholder__label">{manifest.name}</span>
      <h2>Not connected</h2>
      <p>
        The assistant interface will be designed after the local runtime is connected.
      </p>
    </div>
  )
}

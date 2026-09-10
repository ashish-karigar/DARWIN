import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Button } from '../../components/ui'
import {
  defaultPreferences,
  useSettingsStore,
  type ServiceState
} from '../../stores/settingsStore'

interface SettingsAppProps {
  onClose?: () => void
}

type SettingsSection =
  'general' | 'appearance' | 'input' | 'assistant' | 'services' | 'privacy' | 'about'

const sections: { id: SettingsSection; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'appearance', label: 'Appearance' },
  { id: 'input', label: 'Input' },
  { id: 'assistant', label: 'Assistant' },
  { id: 'services', label: 'Services' },
  { id: 'privacy', label: 'Privacy' },
  { id: 'about', label: 'About' }
]

interface CredentialDraft {
  groqApiKey: string
  fishAudioApiKey: string
  spotifyClientId: string
  spotifyClientSecret: string
  ollama: boolean
}

const emptyDraft: CredentialDraft = {
  groqApiKey: '',
  fishAudioApiKey: '',
  spotifyClientId: '',
  spotifyClientSecret: '',
  ollama: true
}

const getCredentialBridge = () => window.darwinHost?.credentials

async function storeCredentials(draft: CredentialDraft): Promise<ServiceState> {
  const credentials = getCredentialBridge()
  if (!credentials) throw new Error('credential_bridge_unavailable')
  const storeIfPresent = async (id: string, secret: string) => {
    if (!secret.trim()) return false
    const result = await credentials.store(id, secret.trim())
    if (!result.ok) throw new Error(result.error ?? 'credential_storage_failed')
    return true
  }

  const [groq, fishAudio, spotifyClientId, spotifyClientSecret] = await Promise.all([
    storeIfPresent('groq.apiKey', draft.groqApiKey),
    storeIfPresent('fishAudio.apiKey', draft.fishAudioApiKey),
    storeIfPresent('spotify.clientId', draft.spotifyClientId),
    storeIfPresent('spotify.clientSecret', draft.spotifyClientSecret)
  ])
  return {
    groq,
    fishAudio,
    spotify: spotifyClientId && spotifyClientSecret,
    ollama: draft.ollama
  }
}

function SetupWizard({ onComplete }: { onComplete?: () => void }) {
  const completeOnboarding = useSettingsStore((state) => state.completeOnboarding)
  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState(emptyDraft)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const finishLater = () => {
    completeOnboarding(defaultPreferences.serviceState)
    onComplete?.()
  }

  const saveServices = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const serviceState = await storeCredentials(draft)
      completeOnboarding(serviceState)
      setDraft(emptyDraft)
      onComplete?.()
    } catch {
      setError(
        'Credentials could not be stored securely. Check the system keychain and try again.'
      )
    } finally {
      setSaving(false)
    }
  }

  if (step === 0) {
    return (
      <div className="setup-wizard">
        <span className="settings-eyebrow">First run</span>
        <h1>Set up Darwin</h1>
        <p>
          Connect the services Darwin already supports. You can change everything later in
          Settings.
        </p>
        <div className="settings-actions">
          <Button variant="primary" onClick={() => setStep(1)}>
            Continue
          </Button>
          <Button variant="ghost" onClick={finishLater}>
            Set up later
          </Button>
        </div>
      </div>
    )
  }

  return (
    <form className="setup-services" onSubmit={saveServices}>
      <span className="settings-eyebrow">Services</span>
      <h1>Connect services</h1>
      <p className="settings-intro">
        Credentials are encrypted using the operating system’s secure storage and never
        saved in browser preferences.
      </p>
      <div className="service-fields">
        <label>
          <span>Groq API key</span>
          <input
            type="password"
            value={draft.groqApiKey}
            autoComplete="off"
            onChange={(event) => setDraft({ ...draft, groqApiKey: event.target.value })}
          />
        </label>
        <label>
          <span>Fish Audio API key</span>
          <input
            type="password"
            value={draft.fishAudioApiKey}
            autoComplete="off"
            onChange={(event) =>
              setDraft({ ...draft, fishAudioApiKey: event.target.value })
            }
          />
        </label>
        <div className="service-fields__pair">
          <label>
            <span>Spotify client ID</span>
            <input
              type="password"
              value={draft.spotifyClientId}
              autoComplete="off"
              onChange={(event) =>
                setDraft({ ...draft, spotifyClientId: event.target.value })
              }
            />
          </label>
          <label>
            <span>Spotify client secret</span>
            <input
              type="password"
              value={draft.spotifyClientSecret}
              autoComplete="off"
              onChange={(event) =>
                setDraft({ ...draft, spotifyClientSecret: event.target.value })
              }
            />
          </label>
        </div>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={draft.ollama}
            onChange={(event) => setDraft({ ...draft, ollama: event.target.checked })}
          />
          <span>Use local Ollama at localhost:11434</span>
        </label>
      </div>
      {error && (
        <p className="settings-error" role="alert">
          {error}
        </p>
      )}
      <div className="settings-actions">
        <Button variant="primary" type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Finish setup'}
        </Button>
        <Button variant="ghost" onClick={() => setStep(0)}>
          Back
        </Button>
      </div>
    </form>
  )
}

function SettingsContent({ section }: { section: SettingsSection }) {
  const settings = useSettingsStore()

  if (section === 'general')
    return (
      <SettingsGroup
        title="General"
        description="Behavior shared across the Darwin shell."
      >
        <SettingRow label="Remember window positions">
          <input
            aria-label="Remember window positions"
            type="checkbox"
            checked={settings.rememberWindowPositions}
            onChange={(event) =>
              settings.setRememberWindowPositions(event.target.checked)
            }
          />
        </SettingRow>
      </SettingsGroup>
    )
  if (section === 'appearance')
    return (
      <SettingsGroup
        title="Appearance"
        description="Keep the interface quiet and readable."
      >
        <SettingRow label="Theme">
          <select
            aria-label="Theme"
            value={settings.theme}
            onChange={(event) =>
              settings.setTheme(event.target.value as 'system' | 'dark' | 'projector')
            }
          >
            <option value="system">System</option>
            <option value="dark">Dark</option>
            <option value="projector">Projector black</option>
          </select>
        </SettingRow>
        <SettingRow label="Reduce motion">
          <input
            aria-label="Reduce motion"
            type="checkbox"
            checked={settings.reducedMotion}
            onChange={(event) => settings.setReducedMotion(event.target.checked)}
          />
        </SettingRow>
        <SettingRow label="Core brightness">
          <label className="settings-range">
            <input
              aria-label="Core brightness"
              type="range"
              min="0.5"
              max="8"
              step="0.1"
              value={settings.neuralBrightness}
              onChange={(event) =>
                settings.setNeuralBrightness(Number(event.target.value))
              }
            />
            <output>{settings.neuralBrightness.toFixed(1)}×</output>
          </label>
        </SettingRow>
        <SettingRow label="Core thickness">
          <label className="settings-range">
            <input
              aria-label="Core thickness"
              type="range"
              min="0.5"
              max="5"
              step="0.1"
              value={settings.neuralThickness}
              onChange={(event) =>
                settings.setNeuralThickness(Number(event.target.value))
              }
            />
            <output>{settings.neuralThickness.toFixed(1)}×</output>
          </label>
        </SettingRow>
        <SettingRow label="Core warmth">
          <label className="settings-range">
            <input
              aria-label="Core warmth"
              type="range"
              min="0"
              max="10"
              step="0.1"
              value={settings.neuralWarmth}
              onChange={(event) => settings.setNeuralWarmth(Number(event.target.value))}
            />
            <output>{settings.neuralWarmth.toFixed(1)}</output>
          </label>
        </SettingRow>
      </SettingsGroup>
    )
  if (section === 'input')
    return (
      <SettingsGroup
        title="Input"
        description="Choose the primary way you operate Darwin."
      >
        <SettingRow label="Primary input">
          <select
            aria-label="Primary input"
            value={settings.primaryInput}
            onChange={(event) =>
              settings.setPrimaryInput(event.target.value as 'mouse' | 'gesture')
            }
          >
            <option value="mouse">Mouse and keyboard</option>
            <option value="gesture">Gesture control</option>
          </select>
        </SettingRow>
      </SettingsGroup>
    )
  if (section === 'assistant')
    return (
      <SettingsGroup title="Assistant" description="Voice and conversation preferences.">
        <SettingRow label="Voice output">
          <input
            aria-label="Voice output"
            type="checkbox"
            checked={settings.voiceEnabled}
            onChange={(event) => settings.setVoiceEnabled(event.target.checked)}
          />
        </SettingRow>
      </SettingsGroup>
    )
  if (section === 'services') return <ServiceSettings />
  if (section === 'privacy')
    return (
      <SettingsGroup
        title="Privacy"
        description="Credentials are encrypted by the host operating system."
      >
        <p className="settings-copy">
          DARWIN preferences contain configuration flags only. API keys and client secrets
          are stored separately through Electron secure storage.
        </p>
      </SettingsGroup>
    )
  return (
    <SettingsGroup
      title="About"
      description="Distributed Agentic Reasoning and Workflow Intelligence Network."
    >
      <SettingRow label="Interface version">
        <span>0.1.0</span>
      </SettingRow>
      <SettingRow label="Backend version">
        <span>Not connected</span>
      </SettingRow>
      <SettingRow label="Protocol">
        <span>1.0</span>
      </SettingRow>
    </SettingsGroup>
  )
}

function ServiceSettings() {
  const serviceState = useSettingsStore((state) => state.serviceState)
  const setServiceConfigured = useSettingsStore((state) => state.setServiceConfigured)
  const [draft, setDraft] = useState({ ...emptyDraft, ollama: serviceState.ollama })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(() =>
    getCredentialBridge()
      ? null
      : 'Secure credential service unavailable. Restart DARWIN and try again.'
  )

  useEffect(() => {
    const credentials = getCredentialBridge()
    if (!credentials) return
    void Promise.all([
      credentials.has('groq.apiKey'),
      credentials.has('fishAudio.apiKey'),
      credentials.has('spotify.clientId'),
      credentials.has('spotify.clientSecret')
    ])
      .then(([groq, fishAudio, spotifyId, spotifySecret]) => {
        setServiceConfigured('groq', groq)
        setServiceConfigured('fishAudio', fishAudio)
        setServiceConfigured('spotify', spotifyId && spotifySecret)
      })
      .catch(() => setMessage('Could not read secure credential status.'))
  }, [setServiceConfigured])

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      const credentials = getCredentialBridge()
      if (!credentials) throw new Error('credential_bridge_unavailable')
      if (draft.groqApiKey.trim())
        await storeCredential(credentials, 'groq.apiKey', draft.groqApiKey)
      if (draft.fishAudioApiKey.trim())
        await storeCredential(credentials, 'fishAudio.apiKey', draft.fishAudioApiKey)
      if (draft.spotifyClientId.trim())
        await storeCredential(credentials, 'spotify.clientId', draft.spotifyClientId)
      if (draft.spotifyClientSecret.trim())
        await storeCredential(
          credentials,
          'spotify.clientSecret',
          draft.spotifyClientSecret
        )

      const [groq, fishAudio, spotifyId, spotifySecret] = await Promise.all([
        credentials.has('groq.apiKey'),
        credentials.has('fishAudio.apiKey'),
        credentials.has('spotify.clientId'),
        credentials.has('spotify.clientSecret')
      ])
      setServiceConfigured('groq', groq)
      setServiceConfigured('fishAudio', fishAudio)
      setServiceConfigured('spotify', spotifyId && spotifySecret)
      setServiceConfigured('ollama', draft.ollama)
      setDraft({ ...emptyDraft, ollama: draft.ollama })
      setMessage('Service settings saved.')
    } catch {
      setMessage('Could not update secure credentials.')
    } finally {
      setSaving(false)
    }
  }

  const disconnect = async (service: 'groq' | 'fishAudio' | 'spotify') => {
    const credentials = getCredentialBridge()
    if (!credentials) {
      setMessage('Secure credential service unavailable. Restart DARWIN and try again.')
      return
    }
    const ids =
      service === 'spotify'
        ? ['spotify.clientId', 'spotify.clientSecret']
        : [service === 'groq' ? 'groq.apiKey' : 'fishAudio.apiKey']
    try {
      const results = await Promise.all(ids.map((id) => credentials.remove(id)))
      if (results.some((result) => !result.ok))
        throw new Error('credential_remove_failed')
      setServiceConfigured(service, false)
      setMessage(`${service === 'fishAudio' ? 'Fish Audio' : service} disconnected.`)
    } catch {
      setMessage('Could not remove the credential.')
    }
  }

  return (
    <SettingsGroup
      title="Services"
      description="Add or replace credentials. Existing secrets are never displayed."
    >
      <form className="services-editor service-fields" onSubmit={save}>
        <ServiceField
          label="Groq API key"
          configured={serviceState.groq}
          value={draft.groqApiKey}
          onChange={(groqApiKey) => setDraft({ ...draft, groqApiKey })}
          onDisconnect={() => void disconnect('groq')}
        />
        <ServiceField
          label="Fish Audio API key"
          configured={serviceState.fishAudio}
          value={draft.fishAudioApiKey}
          onChange={(fishAudioApiKey) => setDraft({ ...draft, fishAudioApiKey })}
          onDisconnect={() => void disconnect('fishAudio')}
        />
        <div className="service-credential-field">
          <div className="service-field-heading">
            <span>Spotify credentials</span>
            <ServiceStatus configured={serviceState.spotify} />
          </div>
          <div className="service-fields__pair">
            <input
              aria-label="Spotify client ID"
              type="password"
              placeholder="Client ID"
              value={draft.spotifyClientId}
              onChange={(event) =>
                setDraft({ ...draft, spotifyClientId: event.target.value })
              }
            />
            <input
              aria-label="Spotify client secret"
              type="password"
              placeholder="Client secret"
              value={draft.spotifyClientSecret}
              onChange={(event) =>
                setDraft({ ...draft, spotifyClientSecret: event.target.value })
              }
            />
          </div>
          {serviceState.spotify && (
            <Button
              type="button"
              variant="ghost"
              className="service-disconnect"
              onClick={() => void disconnect('spotify')}
            >
              Disconnect
            </Button>
          )}
        </div>
        <label className="settings-check services-ollama">
          <input
            type="checkbox"
            aria-label="Use local Ollama"
            checked={draft.ollama}
            onChange={(event) => setDraft({ ...draft, ollama: event.target.checked })}
          />
          <span>Use local Ollama at localhost:11434</span>
        </label>
        {message && (
          <p className="settings-message" role="status">
            {message}
          </p>
        )}
        <div className="settings-actions">
          <Button type="submit" variant="primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </form>
    </SettingsGroup>
  )
}

async function storeCredential(
  credentials: NonNullable<Window['darwinHost']>['credentials'],
  id: string,
  value: string
) {
  const result = await credentials.store(id, value.trim())
  if (!result.ok) throw new Error(result.error ?? 'credential_storage_failed')
}

function ServiceStatus({ configured }: { configured: boolean }) {
  return (
    <span className="service-state" data-configured={configured}>
      {configured ? 'Configured' : 'Not configured'}
    </span>
  )
}

function ServiceField({
  label,
  configured,
  value,
  onChange,
  onDisconnect
}: {
  label: string
  configured: boolean
  value: string
  onChange: (value: string) => void
  onDisconnect: () => void
}) {
  return (
    <div className="service-credential-field">
      <div className="service-field-heading">
        <span>{label}</span>
        <ServiceStatus configured={configured} />
      </div>
      <input
        aria-label={label}
        type="password"
        placeholder={configured ? 'Enter a new key to replace it' : 'Enter API key'}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {configured && (
        <Button
          type="button"
          variant="ghost"
          className="service-disconnect"
          onClick={onDisconnect}
        >
          Disconnect
        </Button>
      )}
    </div>
  )
}

function SettingsGroup({
  children,
  description,
  title
}: {
  children: ReactNode
  description: string
  title: string
}) {
  return (
    <section className="settings-group">
      <header>
        <h1>{title}</h1>
        <p>{description}</p>
      </header>
      <div className="settings-group__rows">{children}</div>
    </section>
  )
}

function SettingRow({ children, label }: { children: ReactNode; label: string }) {
  return (
    <label className="settings-row">
      <span>{label}</span>
      <span>{children}</span>
    </label>
  )
}

export function SettingsApp({ onClose }: SettingsAppProps) {
  const onboardingComplete = useSettingsStore((state) => state.onboardingComplete)
  const reset = useSettingsStore((state) => state.reset)
  const [section, setSection] = useState<SettingsSection>('general')

  if (!onboardingComplete)
    return (
      <div className="settings-fullscreen settings-fullscreen--setup">
        <SetupWizard onComplete={onClose} />
      </div>
    )

  return (
    <div className="settings-fullscreen">
      <header className="settings-header">
        <span>DARWIN / SETTINGS</span>
        {onClose && (
          <button type="button" aria-label="Close Settings" onClick={onClose}>
            ×
          </button>
        )}
      </header>
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          {sections.map((item) => (
            <button
              key={item.id}
              type="button"
              data-active={section === item.id}
              onClick={() => setSection(item.id)}
            >
              {item.label}
            </button>
          ))}
          <button
            type="button"
            className="settings-reset"
            onClick={() => {
              if (window.confirm('Reset all DARWIN preferences?')) reset()
            }}
          >
            Reset settings
          </button>
        </nav>
        <main className="settings-content">
          <SettingsContent section={section} />
        </main>
      </div>
    </div>
  )
}

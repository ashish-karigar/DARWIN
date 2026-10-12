import { useCallback, useEffect, useRef, useState } from 'react'
import { useConversationStore } from '../stores/conversationStore'
import { useAssistantStore } from '../stores/assistantStore'
import type { ConversationEntry } from '../stores/conversationStore'

const normalizeAssistantFormatting = (content: string) =>
  content.replace(/\\([*_`])/g, '$1').replace(/\*{3,}/g, '**')

const renderInlineFormatting = (content: string) =>
  content.split(/(\*\*[^*\n]+\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={index}>{part.slice(2, -2)}</strong>
    ) : (
      part
    )
  )

function MessageText({
  message,
  onProgress
}: {
  message: ConversationEntry
  onProgress: () => void
}) {
  const content = normalizeAssistantFormatting(message.content)
  const animate =
    message.role === 'darwin' &&
    message.status === 'complete'
  const [visibleLength, setVisibleLength] = useState(animate ? 0 : content.length)

  useEffect(() => {
    if (!animate) return
    const step = Math.max(2, Math.ceil(content.length / 90))
    const timer = window.setInterval(() => {
      setVisibleLength((current) => {
        const next = Math.min(content.length, current + step)
        if (next === content.length) window.clearInterval(timer)
        return next
      })
      window.requestAnimationFrame(onProgress)
    }, 18)
    return () => window.clearInterval(timer)
  }, [animate, content, onProgress])

  const streaming = visibleLength < content.length
  const visibleContent = content
    .slice(0, visibleLength)
    .replace(streaming ? /\*{1,2}$/ : /$^/, '')

  return (
    <p data-streaming={streaming}>
      {renderInlineFormatting(visibleContent)}
    </p>
  )
}

export function TranscriptRail() {
  const messages = useConversationStore((state) => state.messages)
  const runtimeStatus = useConversationStore((state) => state.runtimeStatus)
  const activeRequestId = useConversationStore((state) => state.activeRequestId)
  const assistantState = useAssistantStore((state) => state.state)
  const pendingConfirmation = useConversationStore((state) => state.pendingConfirmation)
  const submit = useConversationStore((state) => state.submit)
  const listen = useConversationStore((state) => state.listen)
  const cancel = useConversationStore((state) => state.cancel)
  const resolveConfirmation = useConversationStore((state) => state.resolveConfirmation)
  const clear = useConversationStore((state) => state.clear)
  const [draft, setDraft] = useState('')
  const [manualListening, setManualListening] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const micFeedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const scrollToEnd = useCallback(() => {
    if (typeof endRef.current?.scrollIntoView === 'function') {
      endRef.current.scrollIntoView({ block: 'nearest' })
    }
  }, [])

  useEffect(() => {
    scrollToEnd()
  }, [messages, scrollToEnd])
  useEffect(() => {
    const focus = () => composerRef.current?.focus()
    window.addEventListener('darwin:focus-transcript', focus)
    return () => {
      window.removeEventListener('darwin:focus-transcript', focus)
      if (micFeedbackTimerRef.current) clearTimeout(micFeedbackTimerRef.current)
    }
  }, [])

  const isProcessing = Boolean(activeRequestId)
  const micActive =
    manualListening || assistantState === 'listening' || assistantState === 'transcribing'

  const send = async () => {
    if (await submit(draft)) setDraft('')
  }

  return (
    <aside className="transcript-rail" aria-label="DARWIN conversation">
      <div className="transcript-rail__messages" aria-live="polite">
        {messages.map((message) => (
          <article key={message.id} data-role={message.role} data-status={message.status}>
            <span>{message.role === 'human' ? 'You' : 'DARWIN'}</span>
            <MessageText message={message} onProgress={scrollToEnd} />
            {message.role === 'human' && message.status === 'error' && (
              <button
                type="button"
                aria-label="Retry message"
                title="Retry"
                onClick={() => void submit(message.content)}
              >
                ↻
              </button>
            )}
          </article>
        ))}
        <div ref={endRef} />
      </div>
      {pendingConfirmation && (
        <section className="transcript-confirmation" aria-label="Confirmation required">
          <small>{pendingConfirmation.risk.replaceAll('_', ' ')}</small>
          <p>{pendingConfirmation.summary}</p>
          <div>
            <button type="button" onClick={() => void resolveConfirmation(false)}>
              Cancel
            </button>
            <button type="button" onClick={() => void resolveConfirmation(true)}>
              Allow
            </button>
          </div>
        </section>
      )}
      {messages.length === 0 && (
        <p className="transcript-rail__empty">
          Your conversation with DARWIN lives here.
        </p>
      )}
      <form
        className="transcript-composer"
        onSubmit={(event) => {
          event.preventDefault()
          if (activeRequestId) void cancel(activeRequestId)
          else void send()
        }}
      >
        <button
          type="button"
          className="transcript-composer__clear"
          aria-label="Clear visible chat"
          title="Clear visible chat"
          disabled={messages.length === 0}
          onClick={clear}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 6h16M9 6V4h6v2m-8 0 1 14h8l1-14M10 10v6m4-6v6" />
          </svg>
        </button>
        <textarea
          ref={composerRef}
          aria-label="Message DARWIN"
          value={draft}
          rows={1}
          placeholder={runtimeStatus === 'connected' ? 'Message DARWIN' : 'Connecting…'}
          disabled={runtimeStatus !== 'connected' || isProcessing}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && draft.trim()) {
              event.preventDefault()
              void send()
            }
          }}
        />
        <button
          type="button"
          className="transcript-composer__mic"
          data-active={micActive}
          aria-label="Speak to DARWIN"
          title="Speak to DARWIN"
          disabled={runtimeStatus !== 'connected'}
          onClick={() => {
            setManualListening(true)
            if (micFeedbackTimerRef.current) clearTimeout(micFeedbackTimerRef.current)
            micFeedbackTimerRef.current = setTimeout(() => {
              setManualListening(false)
              micFeedbackTimerRef.current = null
            }, 900)
            void listen().then((started) => {
              if (!started) {
                setManualListening(false)
                if (micFeedbackTimerRef.current) {
                  clearTimeout(micFeedbackTimerRef.current)
                  micFeedbackTimerRef.current = null
                }
              }
            })
          }}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z" />
            <path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3m-4 0h8" />
          </svg>
        </button>
        <button
          type="submit"
          className="transcript-composer__action"
          data-mode={isProcessing ? 'stop' : 'send'}
          aria-label={isProcessing ? 'Stop response' : 'Send message'}
          title={isProcessing ? 'Stop' : 'Send'}
          disabled={
            runtimeStatus !== 'connected' || (!isProcessing && !draft.trim())
          }
        >
          {isProcessing ? (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="7" y="7" width="10" height="10" rx="1.5" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="m4 12 15-7-4 14-3-6-8-1Z" />
              <path d="m12 13 7-8" />
            </svg>
          )}
        </button>
      </form>
    </aside>
  )
}

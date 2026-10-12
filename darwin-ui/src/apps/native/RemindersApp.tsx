import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Button } from '../../components/ui'

interface Reminder {
  id: string
  title: string
  dueDate?: string
  completed: boolean
  list: string
  calendarId: string
  notes?: string
  priority: number
  recurrence?: string
}
interface ReminderList {
  id: string
  title: string
}
interface MailRule {
  id: string
  sender: string
  mailbox: string
  enabled: boolean
}
interface TaskCandidate {
  id: string
  messageId: string
  sender: string
  subject: string
  receivedAt: string
  account: string
  mailbox: string
  title: string
  dueDate: string | null
  priority: 0 | 1 | 5 | 9
  notes: string
  confidence: number
  reason: string
}
type View =
  | 'review'
  | 'rules'
  | 'all'
  | 'today'
  | 'upcoming'
  | 'overdue'
  | 'no-date'
  | 'completed'
  | `list:${string}`
const bridge = () => window.darwinReminders
const taskBridge = () => window.darwinTasks
const TASK_SETTINGS_KEY = 'darwin.task-ingestion.v1'
const DEFAULT_MODEL = 'qwen3:14b'
const DEFAULT_RULE: MailRule = {
  id: 'penn-state-health',
  sender: 'yyang1@pennstatehealth.psu.edu',
  mailbox: 'INBOX',
  enabled: true
}
const readTaskSettings = (): {
  rules: MailRule[]
  candidates: TaskCandidate[]
  processedMessageIds: string[]
} => {
  try {
    const saved = JSON.parse(localStorage.getItem(TASK_SETTINGS_KEY) ?? '') as {
      rules?: MailRule[]
      candidates?: TaskCandidate[]
      processedMessageIds?: string[]
    }
    return {
      rules: saved.rules?.length ? saved.rules : [DEFAULT_RULE],
      candidates: saved.candidates ?? [],
      processedMessageIds: saved.processedMessageIds ?? []
    }
  } catch {
    return { rules: [DEFAULT_RULE], candidates: [], processedMessageIds: [] }
  }
}
const isToday = (date?: string) =>
  Boolean(date && new Date(date).toDateString() === new Date().toDateString())

export function RemindersApp() {
  const [initialTaskSettings] = useState(readTaskSettings)
  const [status, setStatus] = useState('loading'),
    [items, setItems] = useState<Reminder[]>([])
  const [reminderLists, setReminderLists] = useState<ReminderList[]>([])
  const [view, setView] = useState<View>('all'),
    [title, setTitle] = useState('')
  const [dueDate, setDueDate] = useState(''),
    [calendarId, setCalendarId] = useState('')
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState(''),
    [selectedId, setSelectedId] = useState<string | null>(null)
  const [rules, setRules] = useState<MailRule[]>(initialTaskSettings.rules)
  const [candidates, setCandidates] = useState<TaskCandidate[]>(
    initialTaskSettings.candidates
  )
  const [processedMessageIds, setProcessedMessageIds] = useState<string[]>(
    initialTaskSettings.processedMessageIds
  )
  const [mailStatus, setMailStatus] = useState<'unknown' | 'connected' | 'denied'>(
    'unknown'
  )
  const [scanStatus, setScanStatus] = useState('')
  const load = useCallback(async () => {
    if (!bridge()) {
      setStatus('unavailable')
      return
    }
    const access = (await bridge()!.invoke({ action: 'status' })) as {
      status?: string
      error?: string
    }
    setStatus(access.status ?? 'unavailable')
    if (access.error) setError(access.error)
    if (access.status === 'fullAccess') {
      await bridge()!.invoke({ action: 'ensureList', title: 'DARWIN' })
      const result = (await bridge()!.invoke({ action: 'list' })) as {
        reminders?: Reminder[]
        lists?: ReminderList[]
      }
      setItems(result.reminders ?? [])
      setReminderLists(result.lists ?? [])
    }
  }, [])
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])
  useEffect(() => {
    const refreshWhenActive = () => {
      if (document.visibilityState === 'visible') void load()
    }
    window.addEventListener('focus', refreshWhenActive)
    document.addEventListener('visibilitychange', refreshWhenActive)
    return () => {
      window.removeEventListener('focus', refreshWhenActive)
      document.removeEventListener('visibilitychange', refreshWhenActive)
    }
  }, [load])
  useEffect(() => {
    localStorage.setItem(
      TASK_SETTINGS_KEY,
      JSON.stringify({
        rules,
        candidates,
        processedMessageIds: processedMessageIds.slice(-1_000)
      })
    )
  }, [candidates, processedMessageIds, rules])
  const lists = useMemo<Array<[string, string]>>(
    () => reminderLists.map((item) => [item.id, item.title]),
    [reminderLists]
  )
  const darwinCalendarId =
    reminderLists.find((list) => list.title === 'DARWIN')?.id ?? ''
  const selectedCalendarId = calendarId || darwinCalendarId || lists[0]?.[0] || ''
  const matches = (item: Reminder, target: View) =>
    target === 'completed'
      ? item.completed
      : item.completed
        ? false
        : target === 'today'
          ? isToday(item.dueDate)
          : target === 'upcoming'
            ? Boolean(
                item.dueDate &&
                new Date(item.dueDate) > new Date() &&
                !isToday(item.dueDate)
              )
            : target === 'overdue'
              ? Boolean(
                  item.dueDate &&
                  new Date(item.dueDate) < new Date() &&
                  !isToday(item.dueDate)
                )
              : target === 'no-date'
                ? !item.dueDate
                : target.startsWith('list:')
                  ? item.calendarId === target.slice(5)
                  : true
  const visible = useMemo(
    () =>
      items
        .filter(
          (i) =>
            matches(i, view) &&
            (!search ||
              `${i.title} ${i.notes ?? ''}`.toLowerCase().includes(search.toLowerCase()))
        )
        .sort((a, b) => (a.dueDate ?? '9999').localeCompare(b.dueDate ?? '9999')),
    [items, search, view]
  )
  const connect = async () => {
    setBusy(true)
    setError(null)
    const result = (await bridge()?.invoke({ action: 'requestAccess' })) as {
      ok?: boolean
      error?: string
    }
    await load()
    if (!result?.ok) setError(result?.error ?? 'connection_failed')
    setBusy(false)
  }
  const add = async (event: FormEvent) => {
    event.preventDefault()
    if (!title.trim()) return
    setBusy(true)
    await bridge()?.invoke({
      action: 'create',
      title: title.trim(),
      ...(selectedCalendarId ? { calendarId: selectedCalendarId } : {}),
      ...(dueDate ? { dueDate: new Date(`${dueDate}T09:00:00`).toISOString() } : {})
    })
    setTitle('')
    setDueDate('')
    await load()
    setBusy(false)
  }
  const complete = async (item: Reminder) => {
    await bridge()?.invoke({
      action: 'complete',
      id: item.id,
      completed: !item.completed
    })
    await load()
  }
  const remove = async (id: string) => {
    await bridge()?.invoke({ action: 'delete', id })
    await load()
  }
  const connectMail = async () => {
    setBusy(true)
    setError(null)
    const result = (await taskBridge()?.invoke({ action: 'requestMailAccess' })) as {
      ok?: boolean
      error?: string
    }
    if (result?.ok) {
      setMailStatus('connected')
    } else {
      setMailStatus('denied')
      setError(result?.error ?? 'mail_connection_failed')
    }
    setBusy(false)
  }
  const scanMail = async () => {
    if (!taskBridge()) {
      setError('task_service_unavailable')
      return
    }
    setBusy(true)
    setError(null)
    setScanStatus('Reading matching mail…')
    const result = (await taskBridge()!.invoke({
      action: 'scan',
      rules: rules
        .filter((rule) => rule.sender.trim() && rule.mailbox.trim())
        .map((rule) => ({
          ...rule,
          sender: rule.sender.trim(),
          mailbox: rule.mailbox.trim()
        })),
      seenMessageIds: processedMessageIds,
      model: DEFAULT_MODEL
    })) as {
      ok?: boolean
      error?: string
      candidates?: TaskCandidate[]
      processedMessageIds?: string[]
    }
    if (result.ok) {
      setMailStatus('connected')
      setCandidates((current) => [
        ...current,
        ...(result.candidates ?? []).filter(
          (candidate) => !current.some((item) => item.messageId === candidate.messageId)
        )
      ])
      setProcessedMessageIds((current) => [
        ...current,
        ...(result.processedMessageIds ?? [])
      ])
      setScanStatus(
        result.candidates?.length
          ? `${result.candidates.length} new task${result.candidates.length === 1 ? '' : 's'} ready to review.`
          : 'No new tasks found.'
      )
    } else {
      setError(result.error ?? 'mail_scan_failed')
      setScanStatus('')
      if (result.error === 'automation_permission_denied') setMailStatus('denied')
    }
    setBusy(false)
  }
  const approveCandidate = async (candidate: TaskCandidate) => {
    if (!darwinCalendarId) {
      setError('darwin_list_unavailable')
      return
    }
    setBusy(true)
    const result = (await bridge()?.invoke({
      action: 'create',
      title: candidate.title,
      calendarId: darwinCalendarId,
      dueDate: candidate.dueDate,
      priority: candidate.priority,
      notes: [
        candidate.notes,
        `Source: ${candidate.subject} — ${candidate.sender}`
      ]
        .filter(Boolean)
        .join('\n\n')
    })) as { ok?: boolean; error?: string }
    if (result?.ok) {
      setCandidates((current) => current.filter((item) => item.id !== candidate.id))
      await load()
    } else {
      setError(result?.error ?? 'reminder_creation_failed')
    }
    setBusy(false)
  }
  const dismissCandidate = (candidateId: string) => {
    setCandidates((current) => current.filter((item) => item.id !== candidateId))
  }
  const addRule = () => {
    setRules((current) => [
      ...current,
      { id: crypto.randomUUID(), sender: '', mailbox: 'INBOX', enabled: true }
    ])
  }
  const updateRule = (id: string, patch: Partial<MailRule>) => {
    setRules((current) =>
      current.map((rule) => (rule.id === id ? { ...rule, ...patch } : rule))
    )
  }

  if (status === 'loading') return <div className="reminders-state">Loading…</div>
  if (status !== 'fullAccess')
    return (
      <main className="reminders-connect">
        <span>Sync</span>
        <h1>Keep your plans in one place.</h1>
        <p>Connect once to sync with the reminders already on this Mac.</p>
        {error && (
          <p className="reminders-connection-error">
            Connection failed: {error.replaceAll('_', ' ')}
          </p>
        )}
        <Button
          className="reminders-connect__action"
          variant="primary"
          onClick={
            status === 'denied' || status === 'restricted'
              ? () => bridge()?.invoke({ action: 'openSettings' })
              : connect
          }
          disabled={busy}
        >
          {busy
            ? 'Waiting for macOS…'
            : status === 'denied' || status === 'restricted'
              ? 'Open Privacy Settings'
              : 'Connect'}
        </Button>
      </main>
    )

  const views: Array<[View, string]> = [
    ['all', 'All'],
    ['today', 'Today'],
    ['upcoming', 'Upcoming'],
    ['overdue', 'Overdue'],
    ['no-date', 'No date'],
    ['completed', 'Completed']
  ]
  const heading = view.startsWith('list:')
    ? (lists.find(([id]) => id === view.slice(5))?.[1] ?? 'List')
    : view === 'review'
      ? 'Review'
      : view === 'rules'
        ? 'Mail rules'
        : (views.find(([id]) => id === view)?.[1] ?? 'All')
  return (
    <main className="reminders-workspace">
      <aside className="reminders-sidebar">
        <span className="reminders-sidebar__label">Focus</span>
        <nav>
          <button data-active={view === 'review'} onClick={() => setView('review')}>
            <span>Review</span>
            <small>{candidates.length}</small>
          </button>
          {views.map(([id, label]) => (
            <button key={id} data-active={view === id} onClick={() => setView(id)}>
              <span>{label}</span>
              <small>{items.filter((i) => matches(i, id)).length}</small>
            </button>
          ))}
          <button data-active={view === 'rules'} onClick={() => setView('rules')}>
            <span>Mail rules</span>
            <small>{rules.filter((rule) => rule.enabled).length}</small>
          </button>
        </nav>
        {lists.length > 0 && (
          <>
            <span className="reminders-sidebar__label reminders-sidebar__lists">
              Lists
            </span>
            <nav>
              {lists.map(([id, name]) => (
                <button
                  key={id}
                  data-active={view === `list:${id}`}
                  onClick={() => {
                    setView(`list:${id}`)
                    setCalendarId(id)
                  }}
                >
                  <span>{name}</span>
                  <small>
                    {items.filter((i) => !i.completed && i.calendarId === id).length}
                  </small>
                </button>
              ))}
            </nav>
          </>
        )}
        <div className="reminders-sync">
          <i />
          Synced with macOS
        </div>
      </aside>
      <section
        className={`reminders-main${view === 'review' || view === 'rules' ? ' reminders-main--tasks' : ''}`}
      >
        <header>
          <h1>{heading}</h1>
          {view === 'review' ? (
            <button
              className="task-scan-button"
              type="button"
              disabled={busy || !rules.some((rule) => rule.enabled && rule.sender.trim())}
              onClick={scanMail}
            >
              {busy ? 'Scanning…' : 'Scan mail'}
            </button>
          ) : view !== 'rules' ? (
            <label className="reminders-search">
              ⌕
              <input
                aria-label="Search reminders"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search"
              />
            </label>
          ) : null}
        </header>
        {view === 'review' ? (
          <TaskReview
            candidates={candidates}
            error={error}
            scanStatus={scanStatus}
            busy={busy}
            onApprove={approveCandidate}
            onDismiss={dismissCandidate}
          />
        ) : view === 'rules' ? (
          <TaskRules
            rules={rules}
            mailStatus={mailStatus}
            busy={busy}
            error={error}
            onConnect={connectMail}
            onOpenSettings={() => taskBridge()?.invoke({ action: 'openMailSettings' })}
            onAdd={addRule}
            onUpdate={updateRule}
            onRemove={(id) =>
              setRules((current) => current.filter((rule) => rule.id !== id))
            }
          />
        ) : (
          <>
            <form className="reminders-add" onSubmit={add}>
              <span>+</span>
              <input
                aria-label="New reminder"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Add a reminder"
              />
              <input
                aria-label="Due date"
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
              />
              {lists.length > 1 && (
                <select
                  aria-label="Reminder list"
                  value={selectedCalendarId}
                  onChange={(e) => setCalendarId(e.target.value)}
                >
                  {lists.map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              )}
              <button disabled={busy || !title.trim()}>Add</button>
            </form>
            <div className="reminders-list">
              {visible.length === 0 && (
                <p className="reminders-empty">Clear for now.</p>
              )}
              {visible.map((item) => (
                <article
                  key={item.id}
                  className="reminder-row"
                  data-selected={selectedId === item.id}
                  onClick={() => setSelectedId(item.id)}
                >
                  <button
                    type="button"
                    className="reminder-check"
                    aria-label={`${item.completed ? 'Reopen' : 'Complete'} ${item.title}`}
                    data-completed={item.completed}
                    onClick={() => complete(item)}
                  />
                  <div>
                    <strong>{item.title}</strong>
                    <span>
                      {item.list}
                      {item.dueDate
                        ? ` · ${new Date(item.dueDate).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
                        : ''}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="reminder-delete"
                    aria-label={`Delete ${item.title}`}
                    onClick={() => remove(item.id)}
                  >
                    ×
                  </button>
                </article>
              ))}
            </div>
          </>
        )}
      </section>
      {view !== 'review' &&
        view !== 'rules' &&
        selectedId &&
        items.find((i) => i.id === selectedId) && (
        <ReminderDetail
          item={items.find((i) => i.id === selectedId)!}
          lists={lists}
          onClose={() => setSelectedId(null)}
          onSaved={load}
        />
      )}
    </main>
  )
}

function TaskReview({
  candidates,
  error,
  scanStatus,
  busy,
  onApprove,
  onDismiss
}: {
  candidates: TaskCandidate[]
  error: string | null
  scanStatus: string
  busy: boolean
  onApprove: (candidate: TaskCandidate) => Promise<void>
  onDismiss: (candidateId: string) => void
}) {
  return (
    <div className="task-review">
      <div className="task-review__intro">
        <p>Suggested from matching email. Nothing is added until you approve it.</p>
        {scanStatus && <span>{scanStatus}</span>}
        {error && <span data-error="true">{error.replaceAll('_', ' ')}</span>}
      </div>
      {candidates.length === 0 ? (
        <div className="task-review__empty">
          <strong>No suggestions waiting.</strong>
          <span>Scan Apple Mail when you want DARWIN to look for new tasks.</span>
        </div>
      ) : (
        <div className="task-candidates">
          {candidates.map((candidate) => (
            <article className="task-candidate" key={candidate.id}>
              <div className="task-candidate__source">
                <span>{candidate.sender}</span>
                <small>{Math.round(candidate.confidence * 100)}% confidence</small>
              </div>
              <h2>{candidate.title}</h2>
              <p>{candidate.notes || candidate.reason}</p>
              <div className="task-candidate__meta">
                <span>{candidate.subject}</span>
                {candidate.dueDate && (
                  <time>{new Date(candidate.dueDate).toLocaleString()}</time>
                )}
              </div>
              <div className="task-candidate__actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onDismiss(candidate.id)}
                >
                  Dismiss
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void onApprove(candidate)}
                >
                  Add to DARWIN
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

function TaskRules({
  rules,
  mailStatus,
  busy,
  error,
  onConnect,
  onOpenSettings,
  onAdd,
  onUpdate,
  onRemove
}: {
  rules: MailRule[]
  mailStatus: 'unknown' | 'connected' | 'denied'
  busy: boolean
  error: string | null
  onConnect: () => Promise<void>
  onOpenSettings: () => void
  onAdd: () => void
  onUpdate: (id: string, patch: Partial<MailRule>) => void
  onRemove: (id: string) => void
}) {
  return (
    <div className="task-rules">
      <section className="task-rules__connection">
        <div>
          <strong>Apple Mail</strong>
          <span>Read-only · email content stays on this Mac</span>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={mailStatus === 'denied' ? onOpenSettings : () => void onConnect()}
        >
          {mailStatus === 'connected'
            ? 'Connected'
            : mailStatus === 'denied'
              ? 'Open Settings'
              : 'Connect'}
        </button>
      </section>
      {error && <p className="task-rules__error">{error.replaceAll('_', ' ')}</p>}
      <div className="task-rules__heading">
        <div>
          <strong>Rules</strong>
          <span>Only mail matching an enabled rule is examined.</span>
        </div>
        <button type="button" onClick={onAdd}>+</button>
      </div>
      <div className="task-rule-list">
        {rules.map((rule) => (
          <article className="task-rule" key={rule.id}>
            <input
              type="checkbox"
              aria-label="Enable rule"
              checked={rule.enabled}
              onChange={(event) => onUpdate(rule.id, { enabled: event.target.checked })}
            />
            <label>
              Sender
              <input
                value={rule.sender}
                placeholder="person@example.com"
                onChange={(event) => onUpdate(rule.id, { sender: event.target.value })}
              />
            </label>
            <label>
              Mailbox
              <input
                value={rule.mailbox}
                placeholder="INBOX"
                onChange={(event) => onUpdate(rule.id, { mailbox: event.target.value })}
              />
            </label>
            <button
              className="task-rule__remove"
              type="button"
              aria-label="Delete rule"
              onClick={() => onRemove(rule.id)}
            >
              ×
            </button>
          </article>
        ))}
      </div>
      <dl className="task-rules__policy">
        <div><dt>Model</dt><dd>{DEFAULT_MODEL}</dd></div>
        <div><dt>Review</dt><dd>Required before creation</dd></div>
        <div><dt>Destination</dt><dd>Apple Reminders · DARWIN</dd></div>
        <div><dt>Email access</dt><dd>Read-only</dd></div>
      </dl>
    </div>
  )
}

function ReminderDetail({
  item,
  lists,
  onClose,
  onSaved
}: {
  item: Reminder
  lists: Array<[string, string]>
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [draft, setDraft] = useState({
    title: item.title,
    notes: item.notes ?? '',
    dueDate: item.dueDate ? item.dueDate.slice(0, 10) : '',
    calendarId: item.calendarId,
    priority: item.priority,
    recurrence: item.recurrence ?? ''
  })
  const save = async (event: FormEvent) => {
    event.preventDefault()
    await bridge()?.invoke({
      action: 'update',
      id: item.id,
      ...draft,
      dueDate: draft.dueDate ? new Date(`${draft.dueDate}T09:00:00`).toISOString() : ''
    })
    await onSaved()
    onClose()
  }
  return (
    <form className="reminder-detail" onSubmit={save}>
      <header>
        <span>Details</span>
        <button type="button" onClick={onClose}>
          ×
        </button>
      </header>
      <label>
        Title
        <input
          value={draft.title}
          onChange={(e) => setDraft({ ...draft, title: e.target.value })}
        />
      </label>
      <label>
        Notes
        <textarea
          value={draft.notes}
          onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
        />
      </label>
      <label>
        Due
        <input
          type="date"
          value={draft.dueDate}
          onChange={(e) => setDraft({ ...draft, dueDate: e.target.value })}
        />
      </label>
      <label>
        List
        <select
          value={draft.calendarId}
          onChange={(e) => setDraft({ ...draft, calendarId: e.target.value })}
        >
          {lists.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Priority
        <select
          value={draft.priority}
          onChange={(e) => setDraft({ ...draft, priority: Number(e.target.value) })}
        >
          <option value={0}>None</option>
          <option value={1}>High</option>
          <option value={5}>Medium</option>
          <option value={9}>Low</option>
        </select>
      </label>
      <label>
        Repeat
        <select
          value={draft.recurrence}
          onChange={(e) => setDraft({ ...draft, recurrence: e.target.value })}
        >
          <option value="">Never</option>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
          <option value="yearly">Yearly</option>
        </select>
      </label>
      <Button variant="primary" disabled={!draft.title.trim()}>
        Save changes
      </Button>
    </form>
  )
}

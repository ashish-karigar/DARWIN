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
type View =
  'all' | 'today' | 'upcoming' | 'overdue' | 'no-date' | 'completed' | `list:${string}`
const bridge = () => window.darwinReminders
const isToday = (date?: string) =>
  Boolean(date && new Date(date).toDateString() === new Date().toDateString())

export function RemindersApp() {
  const [status, setStatus] = useState('loading'),
    [items, setItems] = useState<Reminder[]>([])
  const [view, setView] = useState<View>('all'),
    [title, setTitle] = useState('')
  const [dueDate, setDueDate] = useState(''),
    [calendarId, setCalendarId] = useState('')
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState(''),
    [selectedId, setSelectedId] = useState<string | null>(null)
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
      const result = (await bridge()!.invoke({ action: 'list' })) as {
        reminders?: Reminder[]
      }
      setItems(result.reminders ?? [])
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
  const lists = useMemo(
    () => Array.from(new Map(items.map((i) => [i.calendarId, i.list])).entries()),
    [items]
  )
  const selectedCalendarId = calendarId || lists[0]?.[0] || ''
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
    : (views.find(([id]) => id === view)?.[1] ?? 'All')
  return (
    <main className="reminders-workspace">
      <aside className="reminders-sidebar">
        <span className="reminders-sidebar__label">Focus</span>
        <nav>
          {views.map(([id, label]) => (
            <button key={id} data-active={view === id} onClick={() => setView(id)}>
              <span>{label}</span>
              <small>{items.filter((i) => matches(i, id)).length}</small>
            </button>
          ))}
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
      <section className="reminders-main">
        <header>
          <h1>{heading}</h1>
          <label className="reminders-search">
            ⌕
            <input
              aria-label="Search reminders"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search"
            />
          </label>
        </header>
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
          {visible.length === 0 && <p className="reminders-empty">Clear for now.</p>}
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
      </section>
      {selectedId && items.find((i) => i.id === selectedId) && (
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

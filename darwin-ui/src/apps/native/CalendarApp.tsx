import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  type CalendarEventDraft,
  type DarwinCalendarEvent,
  useCalendarStore
} from '../../stores/calendarStore'

type CalendarView = 'month' | 'week' | 'day' | 'agenda'

const dayName = new Intl.DateTimeFormat([], { weekday: 'short' })
const monthName = new Intl.DateTimeFormat([], { month: 'long', year: 'numeric' })
const fullDate = new Intl.DateTimeFormat([], { weekday: 'long', month: 'long', day: 'numeric' })
const eventTime = new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' })

const startOfDay = (date: Date) => {
  const value = new Date(date)
  value.setHours(0, 0, 0, 0)
  return value
}

const addDays = (date: Date, count: number) => {
  const value = new Date(date)
  value.setDate(value.getDate() + count)
  return value
}

const startOfWeek = (date: Date) => addDays(startOfDay(date), -startOfDay(date).getDay())

const monthGrid = (date: Date) => {
  const first = new Date(date.getFullYear(), date.getMonth(), 1)
  const start = addDays(first, -first.getDay())
  return Array.from({ length: 42 }, (_, index) => addDays(start, index))
}

const inputValue = (date: Date) => {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

const occursOn = (event: DarwinCalendarEvent, date: Date) => {
  const start = startOfDay(date)
  const end = addDays(start, 1)
  return new Date(event.startDate) < end && new Date(event.endDate) > start
}

export function CalendarApp() {
  const status = useCalendarStore((state) => state.status)
  const calendars = useCalendarStore((state) => state.calendars)
  const events = useCalendarStore((state) => state.events)
  const loading = useCalendarStore((state) => state.loading)
  const error = useCalendarStore((state) => state.error)
  const connect = useCalendarStore((state) => state.connect)
  const openSettings = useCalendarStore((state) => state.openSettings)
  const refresh = useCalendarStore((state) => state.refresh)
  const createEvent = useCalendarStore((state) => state.createEvent)
  const updateEvent = useCalendarStore((state) => state.updateEvent)
  const deleteEvent = useCalendarStore((state) => state.deleteEvent)
  const [view, setView] = useState<CalendarView>('month')
  const [cursor, setCursor] = useState(() => new Date())
  const [selected, setSelected] = useState<DarwinCalendarEvent | 'new' | null>(null)

  const range = useMemo(() => {
    if (view === 'day') return { start: startOfDay(cursor), end: addDays(startOfDay(cursor), 1) }
    if (view === 'week') {
      const start = startOfWeek(cursor)
      return { start, end: addDays(start, 7) }
    }
    const days = monthGrid(cursor)
    return { start: days[0]!, end: addDays(days[41]!, 1) }
  }, [cursor, view])

  const load = useCallback(() => refresh(range.start, range.end), [range.end, range.start, refresh])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const active = () => document.visibilityState === 'visible' && void load()
    window.addEventListener('focus', active)
    document.addEventListener('visibilitychange', active)
    return () => {
      window.removeEventListener('focus', active)
      document.removeEventListener('visibilitychange', active)
    }
  }, [load])

  const move = (direction: number) => {
    const next = new Date(cursor)
    if (view === 'month' || view === 'agenda') next.setMonth(next.getMonth() + direction)
    else next.setDate(next.getDate() + direction * (view === 'week' ? 7 : 1))
    setCursor(next)
  }

  if (status !== 'fullAccess')
    return (
      <section className="calendar-connect">
        <span>CALENDAR</span>
        <h1>Your time, in one place.</h1>
        <p>DARWIN reads the Outlook, Google, and iCloud calendars already connected to this Mac.</p>
        <button type="button" disabled={loading} onClick={() => void connect()}>{loading ? 'Waiting for macOS…' : 'Connect calendars'}</button>
        {(status === 'denied' || status === 'restricted') && <button type="button" className="quiet" onClick={() => void openSettings()}>Open Privacy Settings</button>}
        {error && <small>{error}</small>}
      </section>
    )

  return (
    <section className="calendar-app">
      <header className="calendar-toolbar">
        <div>
          <button type="button" onClick={() => move(-1)} aria-label="Previous period">‹</button>
          <button type="button" onClick={() => setCursor(new Date())}>Today</button>
          <button type="button" onClick={() => move(1)} aria-label="Next period">›</button>
        </div>
        <h1>{view === 'day' ? fullDate.format(cursor) : monthName.format(cursor)}</h1>
        <div>
          {(['month', 'week', 'day', 'agenda'] as const).map((item) => <button type="button" key={item} data-active={view === item} onClick={() => setView(item)}>{item}</button>)}
          <button type="button" className="calendar-add" aria-label="New event" onClick={() => setSelected('new')}>+</button>
        </div>
      </header>
      <div className="calendar-body">
        {view === 'month' ? <MonthView cursor={cursor} events={events} onSelect={setSelected} onPickDay={(date) => { setCursor(date); setView('day') }} /> : <TimelineView view={view} cursor={cursor} events={events} onSelect={setSelected} />}
        {selected && <EventEditor event={selected} calendars={calendars} cursor={cursor} onClose={() => setSelected(null)} onSave={async (draft) => {
          const ok = selected === 'new' ? await createEvent(draft) : await updateEvent(selected.id, draft)
          if (ok) { setSelected(null); await load() }
        }} onDelete={selected === 'new' ? undefined : async () => { if (await deleteEvent(selected.id)) { setSelected(null); await load() } }} />}
      </div>
      {loading && <span className="calendar-loading">Syncing…</span>}
    </section>
  )
}

function MonthView({ cursor, events, onSelect, onPickDay }: { cursor: Date; events: DarwinCalendarEvent[]; onSelect: (event: DarwinCalendarEvent) => void; onPickDay: (date: Date) => void }) {
  const days = monthGrid(cursor)
  return <div className="calendar-month">
    {days.slice(0, 7).map((date) => <span className="calendar-weekday" key={date.toISOString()}>{dayName.format(date)}</span>)}
    {days.map((date) => {
      const matches = events.filter((event) => occursOn(event, date))
      return <div className="calendar-day" data-outside={date.getMonth() !== cursor.getMonth()} data-today={date.toDateString() === new Date().toDateString()} key={date.toISOString()}>
        <button type="button" className="calendar-day__number" onClick={() => onPickDay(date)}>{date.getDate()}</button>
        {matches.slice(0, 3).map((event) => <button type="button" className="calendar-event-chip" key={`${event.id}-${date.toISOString()}`} onClick={() => onSelect(event)}><i style={{ background: event.color }} />{event.title}</button>)}
        {matches.length > 3 && <small>+{matches.length - 3}</small>}
      </div>
    })}
  </div>
}

function TimelineView({ view, cursor, events, onSelect }: { view: CalendarView; cursor: Date; events: DarwinCalendarEvent[]; onSelect: (event: DarwinCalendarEvent) => void }) {
  const start = view === 'day' ? startOfDay(cursor) : view === 'week' ? startOfWeek(cursor) : new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const count = view === 'day' ? 1 : view === 'week' ? 7 : 35
  const days = Array.from({ length: count }, (_, index) => addDays(start, index))
  return <div className="calendar-agenda">
    {days.map((date) => {
      const matches = events.filter((event) => occursOn(event, date))
      if (view === 'agenda' && matches.length === 0) return null
      return <section key={date.toISOString()}>
        <header><strong>{dayName.format(date)}</strong><span>{date.getDate()}</span></header>
        <div>{matches.length ? matches.map((event) => <button type="button" key={`${event.id}-${date.toISOString()}`} onClick={() => onSelect(event)}><i style={{ background: event.color }} /><time>{event.allDay ? 'All day' : eventTime.format(new Date(event.startDate))}</time><span><strong>{event.title}</strong>{event.location && <small>{event.location}</small>}</span></button>) : <small>Open</small>}</div>
      </section>
    })}
  </div>
}

function EventEditor({ event, calendars, cursor, onClose, onSave, onDelete }: { event: DarwinCalendarEvent | 'new'; calendars: ReturnType<typeof useCalendarStore.getState>['calendars']; cursor: Date; onClose: () => void; onSave: (draft: CalendarEventDraft) => Promise<void>; onDelete?: () => Promise<void> }) {
  const writable = calendars.filter((calendar) => calendar.allowsChanges)
  const initialStart = event === 'new' ? new Date(new Date(cursor).setHours(9, 0, 0, 0)) : new Date(event.startDate)
  const initialEnd = event === 'new' ? new Date(new Date(cursor).setHours(10, 0, 0, 0)) : new Date(event.endDate)
  const [title, setTitle] = useState(event === 'new' ? '' : event.title)
  const [calendarId, setCalendarId] = useState(event === 'new' ? writable[0]?.id ?? '' : event.calendarId)
  const [startDate, setStartDate] = useState(inputValue(initialStart))
  const [endDate, setEndDate] = useState(inputValue(initialEnd))
  const [location, setLocation] = useState(event === 'new' ? '' : event.location ?? '')
  const [notes, setNotes] = useState(event === 'new' ? '' : event.notes ?? '')
  const [allDay, setAllDay] = useState(event === 'new' ? false : event.allDay)
  const submit = (submitEvent: FormEvent) => {
    submitEvent.preventDefault()
    if (!title.trim() || !calendarId) return
    void onSave({ title: title.trim(), calendarId, startDate: new Date(startDate).toISOString(), endDate: new Date(endDate).toISOString(), location, notes, allDay })
  }
  return <aside className="calendar-editor">
    <header><span>{event === 'new' ? 'New event' : 'Event'}</span><button type="button" aria-label="Close event editor" onClick={onClose}>×</button></header>
    <form onSubmit={submit}>
      <input className="calendar-editor__title" aria-label="Event title" placeholder="Event title" value={title} onChange={(change) => setTitle(change.target.value)} autoFocus />
      <label>Calendar<select value={calendarId} onChange={(change) => setCalendarId(change.target.value)}>{writable.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.title} · {calendar.source}</option>)}</select></label>
      <label>Starts<input type="datetime-local" value={startDate} onChange={(change) => setStartDate(change.target.value)} /></label>
      <label>Ends<input type="datetime-local" value={endDate} onChange={(change) => setEndDate(change.target.value)} /></label>
      <label className="calendar-editor__check"><input type="checkbox" checked={allDay} onChange={(change) => setAllDay(change.target.checked)} />All day</label>
      <label>Location<input value={location} onChange={(change) => setLocation(change.target.value)} /></label>
      <label>Notes<textarea value={notes} onChange={(change) => setNotes(change.target.value)} /></label>
      <footer>{onDelete && <button type="button" className="danger" onClick={() => void onDelete()}>Delete</button>}<button type="submit">Save</button></footer>
    </form>
  </aside>
}

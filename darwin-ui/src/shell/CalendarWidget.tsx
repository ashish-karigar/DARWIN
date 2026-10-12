import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { dayBounds, useCalendarStore } from '../stores/calendarStore'

const CalendarGlyph = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <rect x="3.5" y="5" width="17" height="15" rx="3" />
    <path d="M8 3v4M16 3v4M3.5 9.5h17" />
  </svg>
)

const time = new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' })
const day = new Intl.DateTimeFormat([], { weekday: 'long', month: 'short', day: 'numeric' })
const START_HOUR = 6
const END_HOUR = 24
const TOTAL_MINUTES = (END_HOUR - START_HOUR) * 60

const minutesFromStart = (date: Date) =>
  date.getHours() * 60 + date.getMinutes() - START_HOUR * 60

const hourLabel = (hour: number) => {
  if (hour === 12) return '12 PM'
  if (hour > 12) return `${hour - 12} PM`
  return `${hour} AM`
}

export function CalendarWidget({ onOpen }: { onOpen: () => void }) {
  const status = useCalendarStore((state) => state.status)
  const events = useCalendarStore((state) => state.events)
  const loading = useCalendarStore((state) => state.loading)
  const hidden = useCalendarStore((state) => state.widgetHidden)
  const setHidden = useCalendarStore((state) => state.setWidgetHidden)
  const refresh = useCalendarStore((state) => state.refresh)
  const connect = useCalendarStore((state) => state.connect)
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const { start, end } = dayBounds()
    void refresh(start, end)
    const timer = window.setInterval(() => void refresh(start, end), 60_000)
    return () => window.clearInterval(timer)
  }, [refresh])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  const today = useMemo(() => {
    const { start, end } = dayBounds()
    return events
      .filter((event) => new Date(event.endDate) > start && new Date(event.startDate) < end)
      .sort((a, b) => a.startDate.localeCompare(b.startDate))
  }, [events])

  if (hidden)
    return (
      <button className="calendar-widget-peek" type="button" aria-label="Show today's calendar" onClick={() => setHidden(false)}>
        <CalendarGlyph />
        {today.length > 0 && <i>{today.length}</i>}
      </button>
    )

  const timelineEvents = today.filter((event) => {
    if (event.allDay) return true
    const start = minutesFromStart(new Date(event.startDate))
    const end = minutesFromStart(new Date(event.endDate))
    return end > 0 && start < TOTAL_MINUTES
  })
  const eventBoundaries = Array.from(new Set(timelineEvents.flatMap((event) => {
    const rawStart = event.allDay ? 0 : minutesFromStart(new Date(event.startDate))
    const rawEnd = event.allDay ? 60 : minutesFromStart(new Date(event.endDate))
    const start = Math.max(0, rawStart)
    const end = Math.min(TOTAL_MINUTES, Math.max(start + 18, rawEnd))
    return [start, end]
  }))).sort((left, right) => left - right)
  const currentMinute = minutesFromStart(now)

  return (
    <aside className="calendar-widget" aria-label="Today's calendar">
      <header>
        <button type="button" className="calendar-widget__date" onClick={onOpen}>
          <span>{day.format(new Date())}</span>
        </button>
        <button type="button" className="calendar-widget__hide" aria-label="Hide calendar widget" onClick={() => setHidden(true)}>−</button>
      </header>
      {status !== 'fullAccess' ? (
        <button type="button" className="calendar-widget__connect" disabled={loading} onClick={() => void connect()}>
          {loading ? 'Waiting for macOS…' : 'Connect Outlook calendar'}
        </button>
      ) : (
        <div className="calendar-widget__timeline" onDoubleClick={onOpen}>
          <div className="calendar-widget__hours" aria-hidden="true">
            {Array.from({ length: END_HOUR - START_HOUR }, (_, index) => {
              const hourStart = index * 60
              const hourEnd = hourStart + 60
              const hasEvent = timelineEvents.some((event) => {
                const eventStart = event.allDay ? 0 : minutesFromStart(new Date(event.startDate))
                const eventEnd = event.allDay ? 60 : minutesFromStart(new Date(event.endDate))
                return eventEnd > hourStart && eventStart < hourEnd
              })
              return <div key={index} data-has-event={hasEvent}><time>{hourLabel(index + START_HOUR)}</time><i /></div>
            })}
          </div>
          <div className="calendar-widget__event-layer">
            {timelineEvents.map((event) => {
              const rawStart = event.allDay ? 0 : minutesFromStart(new Date(event.startDate))
              const rawEnd = event.allDay ? 60 : minutesFromStart(new Date(event.endDate))
              const start = Math.max(0, rawStart)
              const end = Math.min(TOTAL_MINUTES, Math.max(start + 18, rawEnd))
              const eventStart = new Date(event.startDate)
              const eventEnd = new Date(event.endDate)
              const compact = !event.allDay && eventEnd.getTime() - eventStart.getTime() < 45 * 60_000
              const period = event.allDay || (eventStart <= now && eventEnd > now)
                ? 'current'
                : eventEnd <= now ? 'past' : 'future'
              return (
                <button
                  type="button"
                  className="calendar-widget__event"
                  data-compact={compact}
                  data-period={period}
                  key={`${event.id}-${event.startDate}`}
                  style={{
                    top: `${(start / TOTAL_MINUTES) * 100}%`,
                    height: `${((end - start) / TOTAL_MINUTES) * 100}%`
                  } as CSSProperties}
                  onClick={onOpen}
                >
                  <strong>{event.title}</strong>
                  <small>{event.allDay ? 'All day' : `${time.format(new Date(event.startDate))} – ${time.format(new Date(event.endDate))}`}</small>
                </button>
              )
            })}
            {eventBoundaries.map((minute) => (
              <i
                aria-hidden="true"
                className="calendar-widget__event-divider"
                key={minute}
                style={{ top: `${(minute / TOTAL_MINUTES) * 100}%` }}
              />
            ))}
            {currentMinute >= 0 && currentMinute <= TOTAL_MINUTES && (
              <div className="calendar-widget__now" style={{ top: `${(currentMinute / TOTAL_MINUTES) * 100}%` }}>
                <time>{time.format(now)}</time><i />
              </div>
            )}
          </div>
        </div>
      )}
    </aside>
  )
}

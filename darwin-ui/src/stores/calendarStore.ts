import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface DarwinCalendar {
  id: string
  title: string
  color: string
  source: string
  allowsChanges: boolean
}

export interface DarwinCalendarEvent {
  id: string
  calendarId: string
  calendar: string
  color: string
  source: string
  title: string
  notes?: string
  location?: string
  startDate: string
  endDate: string
  allDay: boolean
}

export interface CalendarEventDraft {
  calendarId: string
  title: string
  notes?: string
  location?: string
  startDate: string
  endDate: string
  allDay?: boolean
}

interface CalendarState {
  status: string
  calendars: DarwinCalendar[]
  events: DarwinCalendarEvent[]
  loading: boolean
  error: string | null
  widgetHidden: boolean
  setWidgetHidden: (hidden: boolean) => void
  connect: () => Promise<void>
  openSettings: () => Promise<void>
  refresh: (rangeStart: Date, rangeEnd: Date) => Promise<void>
  createEvent: (draft: CalendarEventDraft) => Promise<boolean>
  updateEvent: (id: string, draft: CalendarEventDraft) => Promise<boolean>
  deleteEvent: (id: string) => Promise<boolean>
}

const bridge = () => window.darwinCalendar

const messageFor = (error?: string) => {
  if (error === 'helper_unavailable') return 'Calendar bridge is unavailable. Restart DARWIN.'
  if (error === 'access_denied') return 'Calendar access is not enabled.'
  if (error === 'request_timed_out') return 'macOS did not answer the calendar request.'
  return error ? `Calendar error: ${error.replaceAll('_', ' ')}` : null
}

export const useCalendarStore = create<CalendarState>()(
  persist(
    (set) => ({
      status: 'loading',
      calendars: [],
      events: [],
      loading: false,
      error: null,
      widgetHidden: false,
      setWidgetHidden: (widgetHidden) => set({ widgetHidden }),
      connect: async () => {
        const api = bridge()
        if (!api) {
          set({ status: 'unavailable', error: 'Calendar bridge is unavailable.' })
          return
        }
        set({ loading: true, error: null })
        const result = (await api.invoke({ action: 'requestAccess' })) as {
          ok?: boolean
          status?: string
          error?: string
        }
        set({
          loading: false,
          status: result.status ?? (result.ok ? 'fullAccess' : 'denied'),
          error: result.ok ? null : messageFor(result.error)
        })
      },
      openSettings: async () => {
        await bridge()?.invoke({ action: 'openSettings' })
      },
      refresh: async (rangeStart, rangeEnd) => {
        const api = bridge()
        if (!api) {
          set({ status: 'unavailable', error: 'Calendar bridge is unavailable.' })
          return
        }
        set({ loading: true, error: null })
        const access = (await api.invoke({ action: 'status' })) as {
          status?: string
          error?: string
        }
        if (access.status !== 'fullAccess') {
          set({
            loading: false,
            status: access.status ?? 'unavailable',
            error: messageFor(access.error)
          })
          return
        }
        const result = (await api.invoke({
          action: 'list',
          rangeStart: rangeStart.toISOString(),
          rangeEnd: rangeEnd.toISOString()
        })) as {
          ok?: boolean
          calendars?: DarwinCalendar[]
          events?: DarwinCalendarEvent[]
          error?: string
        }
        set({
          status: result.ok ? 'fullAccess' : result.error === 'access_denied' ? 'denied' : 'error',
          loading: false,
          calendars: result.calendars ?? [],
          events: result.events ?? [],
          error: result.ok ? null : messageFor(result.error)
        })
      },
      createEvent: async (draft) => {
        const result = (await bridge()?.invoke({ action: 'create', ...draft })) as {
          ok?: boolean
          error?: string
        } | undefined
        if (!result?.ok) set({ error: messageFor(result?.error) })
        return Boolean(result?.ok)
      },
      updateEvent: async (id, draft) => {
        const result = (await bridge()?.invoke({ action: 'update', id, ...draft })) as {
          ok?: boolean
          error?: string
        } | undefined
        if (!result?.ok) set({ error: messageFor(result?.error) })
        return Boolean(result?.ok)
      },
      deleteEvent: async (id) => {
        const result = (await bridge()?.invoke({ action: 'delete', id })) as {
          ok?: boolean
          error?: string
        } | undefined
        if (!result?.ok) set({ error: messageFor(result?.error) })
        return Boolean(result?.ok)
      }
    }),
    {
      name: 'darwin.calendar.preferences',
      version: 1,
      partialize: (state) => ({ widgetHidden: state.widgetHidden })
    }
  )
)

export const dayBounds = (date = new Date()) => {
  const start = new Date(date)
  start.setHours(0, 0, 0, 0)
  const end = new Date(start)
  end.setDate(end.getDate() + 1)
  return { start, end }
}

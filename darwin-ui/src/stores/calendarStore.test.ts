import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCalendarStore } from './calendarStore'

describe('calendar store', () => {
  const invoke = vi.fn()

  beforeEach(() => {
    invoke.mockReset()
    Object.defineProperty(window, 'darwinCalendar', {
      configurable: true,
      value: { invoke }
    })
    useCalendarStore.setState({
      status: 'loading',
      calendars: [],
      events: [],
      loading: false,
      error: null,
      widgetHidden: false
    })
  })

  it('loads calendars and events from the native bridge', async () => {
    invoke
      .mockResolvedValueOnce({ ok: true, status: 'fullAccess' })
      .mockResolvedValueOnce({
        ok: true,
        calendars: [{ id: 'outlook', title: 'Calendar', color: '#b9965b', source: 'Exchange', allowsChanges: true }],
        events: [{ id: 'event', calendarId: 'outlook', calendar: 'Calendar', color: '#b9965b', source: 'Exchange', title: 'Review', startDate: '2026-09-15T14:00:00.000Z', endDate: '2026-09-15T15:00:00.000Z', allDay: false }]
      })
    await useCalendarStore.getState().refresh(new Date('2026-09-15T00:00:00Z'), new Date('2026-09-16T00:00:00Z'))
    expect(useCalendarStore.getState().calendars[0]?.source).toBe('Exchange')
    expect(useCalendarStore.getState().events[0]?.title).toBe('Review')
  })

  it('passes event creation through to EventKit', async () => {
    invoke.mockResolvedValueOnce({ ok: true, id: 'created' })
    const draft = { calendarId: 'outlook', title: 'Focus', startDate: '2026-09-15T14:00:00.000Z', endDate: '2026-09-15T15:00:00.000Z' }
    await expect(useCalendarStore.getState().createEvent(draft)).resolves.toBe(true)
    expect(invoke).toHaveBeenCalledWith({ action: 'create', ...draft })
  })
})

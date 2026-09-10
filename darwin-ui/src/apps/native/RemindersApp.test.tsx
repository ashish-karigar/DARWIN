import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RemindersApp } from './RemindersApp'

describe('RemindersApp', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('loads, creates, and completes Apple reminders through the bridge', async () => {
    const invoke = vi.fn(async (request: { action: string }) => {
      if (request.action === 'status') return { ok: true, status: 'fullAccess' }
      if (request.action === 'list')
        return {
          ok: true,
          reminders: [{ id: 'one', title: 'Buy tea', completed: false, list: 'Home' }]
        }
      return { ok: true }
    })
    vi.stubGlobal('darwinReminders', { invoke })
    render(<RemindersApp />)

    expect(await screen.findByText('Buy tea')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('New reminder'), {
      target: { value: 'Call Sam' }
    })
    fireEvent.submit(screen.getByLabelText('New reminder').closest('form')!)
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith({ action: 'create', title: 'Call Sam' })
    )
    fireEvent.click(screen.getByRole('button', { name: 'Complete Buy tea' }))
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith({
        action: 'complete',
        id: 'one',
        completed: true
      })
    )
  })

  it('always exposes a connection action before permission is granted', async () => {
    vi.stubGlobal('darwinReminders', {
      invoke: vi.fn(async () => ({ ok: true, status: 'notDetermined' }))
    })
    render(<RemindersApp />)
    expect(await screen.findByRole('button', { name: 'Connect' })).toBeVisible()
  })
})

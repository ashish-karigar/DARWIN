import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RemindersApp } from './RemindersApp'

describe('RemindersApp', () => {
  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

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

  it('reviews an email task before creating it in the DARWIN list', async () => {
    const remindersInvoke = vi.fn(async (request: { action: string }) => {
      if (request.action === 'status') return { ok: true, status: 'fullAccess' }
      if (request.action === 'list')
        return {
          ok: true,
          reminders: [],
          lists: [{ id: 'darwin-list', title: 'DARWIN' }]
        }
      return { ok: true }
    })
    const taskInvoke = vi.fn(async () => ({
      ok: true,
      processedMessageIds: ['mail-1'],
      candidates: [
        {
          id: 'candidate-1',
          messageId: 'mail-1',
          sender: 'yyang1@pennstatehealth.psu.edu',
          subject: 'Please submit the form',
          receivedAt: '2026-09-16',
          account: 'Outlook',
          mailbox: 'INBOX',
          title: 'Submit the signed form',
          dueDate: null,
          priority: 1,
          notes: 'Professor Yang requested the signed form.',
          confidence: 0.94,
          reason: 'A submission is required.'
        }
      ]
    }))
    vi.stubGlobal('darwinReminders', { invoke: remindersInvoke })
    vi.stubGlobal('darwinTasks', { invoke: taskInvoke })
    render(<RemindersApp />)

    await screen.findByRole('heading', { name: 'All' })
    fireEvent.click(screen.getByRole('button', { name: /Review/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Scan mail' }))
    expect(await screen.findByText('Submit the signed form')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Add to DARWIN' }))

    await waitFor(() =>
      expect(remindersInvoke).toHaveBeenCalledWith(
        expect.objectContaining({
          action: 'create',
          title: 'Submit the signed form',
          calendarId: 'darwin-list'
        })
      )
    )
  })
})

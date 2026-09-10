import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppLauncher } from './AppLauncher'
import { shellApps } from './apps'

const defaults = {
  apps: shellApps,
  open: true,
  onClose: vi.fn(),
  onLaunchApp: vi.fn()
}

describe('AppLauncher', () => {
  it('filters applications and shows an empty state', () => {
    render(<AppLauncher {...defaults} />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Search applications' }), {
      target: { value: 'missing' }
    })
    expect(screen.getByText('No applications found.')).toBeInTheDocument()
  })

  it('shows loading and error states', () => {
    const { rerender } = render(<AppLauncher {...defaults} status="loading" />)
    expect(screen.getByText('Loading applications…')).toBeInTheDocument()
    rerender(<AppLauncher {...defaults} status="error" />)
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Applications could not be loaded.'
    )
  })

  it('supports keyboard selection', () => {
    const onLaunchApp = vi.fn()
    render(<AppLauncher {...defaults} onLaunchApp={onLaunchApp} />)
    const search = screen.getByRole('textbox', { name: 'Search applications' })
    fireEvent.keyDown(search, { key: 'ArrowDown' })
    fireEvent.keyDown(search, { key: 'Enter' })
    expect(onLaunchApp).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Reminders' })
    )
  })
})

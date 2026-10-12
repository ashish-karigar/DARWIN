import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SystemStats } from './SystemStats'

describe('SystemStats', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows locally tracked Groq daily usage', async () => {
    Object.defineProperty(window, 'darwinAssistantSession', {
      configurable: true,
      value: {
        getUsage: async () => ({
          available: true,
          used_tokens: 73_420,
          daily_limit_tokens: 200_000,
          remaining_tokens: 126_580,
          request_count: 12,
          reset_at: '2026-09-13T00:00:00+00:00',
          tracked_since: '2026-09-12T12:00:00+00:00',
          scope: 'darwin-local'
        })
      }
    })

    render(<SystemStats />)

    await waitFor(() =>
      expect(screen.getByText('73,420 / 200,000')).toBeInTheDocument()
    )
  })
})

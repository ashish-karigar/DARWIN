import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useConversationStore } from '../stores/conversationStore'
import { StatusBar } from './StatusBar'

describe('StatusBar assistant readiness', () => {
  beforeEach(() => {
    useConversationStore.setState({ runtimeStatus: 'starting' })
  })

  it('shows online only when the authenticated backend is ready', () => {
    const { rerender } = render(<StatusBar theme="dark" onToggleTheme={vi.fn()} />)
    expect(screen.getByText('Assistant starting')).toBeInTheDocument()

    useConversationStore.setState({ runtimeStatus: 'connected' })
    rerender(<StatusBar theme="dark" onToggleTheme={vi.fn()} />)
    expect(screen.getByText('Assistant online')).toBeInTheDocument()
  })
})

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Button, IconButton, Menu, Panel, Tooltip } from '.'

describe('UI primitives', () => {
  it('renders buttons with accessible names', () => {
    render(
      <>
        <Button>Continue</Button>
        <IconButton aria-label="Close">×</IconButton>
      </>
    )
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Close' })).toBeEnabled()
  })

  it('associates a tooltip with its control', () => {
    render(
      <Tooltip content="Open settings">
        <button type="button">Settings</button>
      </Tooltip>
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent('Open settings')
  })

  it('opens a menu and selects an item', () => {
    const onSelect = vi.fn()
    render(<Menu label="Actions" items={[{ id: 'open', label: 'Open', onSelect }]} />)
    fireEvent.click(screen.getByRole('button', { name: /Actions/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Open' }))
    expect(onSelect).toHaveBeenCalledOnce()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes an open menu with Escape', () => {
    render(<Menu label="Actions" items={[]} />)
    fireEvent.click(screen.getByRole('button', { name: /Actions/ }))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('renders panel context and content', () => {
    render(
      <Panel heading="System" description="Local runtime">
        Ready
      </Panel>
    )
    expect(screen.getByRole('heading', { name: 'System' })).toBeInTheDocument()
    expect(screen.getByText('Ready')).toBeInTheDocument()
  })
})

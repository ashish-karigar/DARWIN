import { useEffect, useId, useRef, useState } from 'react'
import { Button } from './Button'

export interface MenuItem {
  id: string
  label: string
  disabled?: boolean
  tone?: 'default' | 'danger'
  onSelect: () => void
}

export interface MenuProps {
  label: string
  items: MenuItem[]
}

export function Menu({ items, label }: MenuProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return

    const handlePointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  return (
    <div ref={containerRef} className="ui-menu">
      <Button
        variant="secondary"
        aria-controls={menuId}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((current) => !current)}
      >
        {label}
        <span aria-hidden="true" className="ui-menu__chevron">
          ↓
        </span>
      </Button>
      {open && (
        <div id={menuId} role="menu" aria-label={label} className="ui-menu__content">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              className="ui-menu__item"
              data-tone={item.tone ?? 'default'}
              onClick={() => {
                item.onSelect()
                setOpen(false)
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

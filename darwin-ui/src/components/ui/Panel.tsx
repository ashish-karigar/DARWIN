import type { HTMLAttributes, ReactNode } from 'react'

export interface PanelProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode
  heading?: string
  description?: string
}

export function Panel({
  children,
  className = '',
  description,
  heading,
  ...props
}: PanelProps) {
  return (
    <section className={`ui-panel ${className}`.trim()} {...props}>
      {(heading || description) && (
        <header className="ui-panel__header">
          {heading && <h2 className="ui-panel__title">{heading}</h2>}
          {description && <p className="ui-panel__description">{description}</p>}
        </header>
      )}
      <div className="ui-panel__content">{children}</div>
    </section>
  )
}

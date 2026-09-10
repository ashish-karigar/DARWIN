import { useId, type ReactElement, type ReactNode } from 'react'

export interface TooltipProps {
  children: ReactElement
  content: ReactNode
  side?: 'top' | 'bottom'
}

export function Tooltip({ children, content, side = 'top' }: TooltipProps) {
  const tooltipId = useId()

  return (
    <span className="ui-tooltip-anchor">
      <span aria-describedby={tooltipId}>{children}</span>
      <span id={tooltipId} role="tooltip" className={`ui-tooltip ui-tooltip--${side}`}>
        {content}
      </span>
    </span>
  )
}

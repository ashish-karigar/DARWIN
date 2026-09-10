import type { WindowBounds } from '../../shared/contracts'

export type ResizeDirection = 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'nw'

export const resizedBounds = (
  initial: WindowBounds,
  direction: ResizeDirection,
  deltaX: number,
  deltaY: number
): WindowBounds => {
  const movesNorth = direction.includes('n')
  const movesSouth = direction.includes('s')
  const movesWest = direction.includes('w')
  const movesEast = direction.includes('e')

  return {
    x: movesWest ? initial.x + deltaX : initial.x,
    y: movesNorth ? initial.y + deltaY : initial.y,
    width: initial.width + (movesEast ? deltaX : 0) - (movesWest ? deltaX : 0),
    height: initial.height + (movesSouth ? deltaY : 0) - (movesNorth ? deltaY : 0)
  }
}

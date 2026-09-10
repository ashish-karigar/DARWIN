import { describe, expect, it } from 'vitest'
import { resizedBounds } from './windowGeometry'

const bounds = { x: 100, y: 80, width: 600, height: 400 }

describe('window resize geometry', () => {
  it('resizes from the southeast corner', () => {
    expect(resizedBounds(bounds, 'se', 50, 30)).toEqual({
      x: 100,
      y: 80,
      width: 650,
      height: 430
    })
  })

  it('moves the origin when resizing from the northwest corner', () => {
    expect(resizedBounds(bounds, 'nw', 40, 20)).toEqual({
      x: 140,
      y: 100,
      width: 560,
      height: 380
    })
  })
})

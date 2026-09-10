import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => cleanup())

HTMLCanvasElement.prototype.getContext = vi.fn(() => null)

Object.defineProperties(HTMLElement.prototype, {
  setPointerCapture: { configurable: true, value: () => undefined },
  releasePointerCapture: { configurable: true, value: () => undefined },
  hasPointerCapture: { configurable: true, value: () => false }
})

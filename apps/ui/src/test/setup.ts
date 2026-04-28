import '@testing-library/jest-dom'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
})

// Mock localStorage for Zustand persist middleware
const localStorageMock = {
  clear: vi.fn(() => undefined),
  getItem: vi.fn(() => null),
  key: vi.fn(() => null),
  length: 0,
  removeItem: vi.fn(() => undefined),
  setItem: vi.fn(() => undefined),
}

Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  writable: true,
})

class MutationObserverMock implements MutationObserver {
  disconnect = vi.fn()
  observe = vi.fn()
  takeRecords = vi.fn(() => [] as MutationRecord[])
}

class ResizeObserverMock implements ResizeObserver {
  disconnect = vi.fn()
  observe = vi.fn()
  unobserve = vi.fn()
}

globalThis.ResizeObserver = ResizeObserverMock
globalThis.MutationObserver = MutationObserverMock

// Mock scrollIntoView for Radix Select
Element.prototype.scrollIntoView = vi.fn()

Object.defineProperty(window, 'matchMedia', {
  value: vi.fn().mockImplementation((query) => ({
    addEventListener: vi.fn(),
    addListener: vi.fn(),
    dispatchEvent: vi.fn(),
    matches: false,
    media: query,
    onchange: null,
    removeEventListener: vi.fn(),
    removeListener: vi.fn(),
  })),
  writable: true,
})

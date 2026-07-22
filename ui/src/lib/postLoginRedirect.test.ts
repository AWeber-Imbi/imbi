import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  isSafeReturnTo,
  performPostLoginRedirect,
  resolvePostLoginTarget,
} from './postLoginRedirect'

const origin = window.location.origin

describe('isSafeReturnTo', () => {
  it('accepts root-relative paths', () => {
    expect(isSafeReturnTo('/dashboard')).toBe(true)
    expect(isSafeReturnTo('/auth/authorize?x=1')).toBe(true)
  })

  it('rejects scheme-relative and backslash tricks', () => {
    expect(isSafeReturnTo('//evil.example')).toBe(false)
    expect(isSafeReturnTo('/\\evil.example')).toBe(false)
  })

  it('accepts same-origin absolute URLs', () => {
    expect(isSafeReturnTo(`${origin}/api/auth/authorize?x=1`)).toBe(true)
  })

  it('rejects cross-origin absolute URLs', () => {
    expect(isSafeReturnTo('https://evil.example/steal')).toBe(false)
  })

  it('rejects empty and non-URL values', () => {
    expect(isSafeReturnTo('')).toBe(false)
    expect(isSafeReturnTo('javascript:alert(1)')).toBe(false)
  })
})

describe('resolvePostLoginTarget', () => {
  it('prefers a valid return_to param', () => {
    expect(resolvePostLoginTarget('/a', '/b')).toBe('/a')
  })

  it('falls back to the stored path when return_to is unsafe', () => {
    expect(resolvePostLoginTarget('https://evil.example', '/b')).toBe('/b')
  })

  it('defaults to the dashboard when nothing is safe', () => {
    expect(resolvePostLoginTarget(null, '//evil')).toBe('/dashboard')
    expect(resolvePostLoginTarget(null, null)).toBe('/dashboard')
  })
})

describe('performPostLoginRedirect', () => {
  const realLocation = window.location

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: realLocation,
    })
    vi.restoreAllMocks()
  })

  it('uses a full-page load for absolute URLs', () => {
    const assign = vi.fn()
    // jsdom forbids spying on location.assign; replace location wholesale.
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { assign },
    })
    const navigate = vi.fn()
    performPostLoginRedirect(`${origin}/api/auth/authorize`, navigate)
    expect(assign).toHaveBeenCalledWith(`${origin}/api/auth/authorize`)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('uses client-side navigation for relative paths', () => {
    const navigate = vi.fn()
    performPostLoginRedirect('/dashboard', navigate)
    expect(navigate).toHaveBeenCalledWith('/dashboard', { replace: true })
  })
})

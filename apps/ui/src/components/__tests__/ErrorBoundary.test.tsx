import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ErrorBoundary } from '../ErrorBoundary'

function Boom({ message }: { message: string }): never {
  throw new Error(message)
}

const RELOAD_GUARD_KEY = 'imbi:error-boundary-reloaded-at'

describe('ErrorBoundary', () => {
  let reloadSpy: ReturnType<typeof vi.fn>
  let originalLocation: Location
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    window.sessionStorage.clear()
    originalLocation = window.location
    reloadSpy = vi.fn()
    // jsdom marks `window.location.reload` as non-configurable, so we replace
    // the whole `location` object for the duration of the test.
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, reload: reloadSpy },
      writable: true,
    })
    // React 18 logs the caught error to console.error in addition to our
    // boundary's own logging — silence the noise so the test output stays
    // readable.
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
      writable: true,
    })
    consoleErrorSpy.mockRestore()
  })

  it('auto-reloads when a dynamic import fails after a redeploy', () => {
    render(
      <ErrorBoundary>
        <Boom message="Failed to fetch dynamically imported module: https://example.com/assets/Page.abc.js" />
      </ErrorBoundary>,
    )

    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('auto-reloads when the server returns text/html for a chunk', () => {
    render(
      <ErrorBoundary>
        <Boom message='Failed to load module script: Expected a JavaScript-or-Wasm module script but the server responded with a MIME type of "text/html".' />
      </ErrorBoundary>,
    )

    expect(reloadSpy).toHaveBeenCalled()
  })

  it('shows the fallback UI for ordinary render errors', () => {
    render(
      <ErrorBoundary>
        <Boom message="Cannot read properties of undefined (reading 'foo')" />
      </ErrorBoundary>,
    )

    expect(reloadSpy).not.toHaveBeenCalled()
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('does not loop: a recent reload disables auto-reload until the guard window passes', () => {
    window.sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))

    render(
      <ErrorBoundary>
        <Boom message="Failed to fetch dynamically imported module" />
      </ErrorBoundary>,
    )

    expect(reloadSpy).not.toHaveBeenCalled()
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})

import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ErrorBoundary } from '../ErrorBoundary'

function Boom({ message }: { message: string }): never {
  throw new Error(message)
}

describe('ErrorBoundary', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    // React 18 logs the caught error to console.error in addition to our
    // boundary's own logging — silence the noise so the test output stays
    // readable.
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    consoleErrorSpy.mockRestore()
  })

  it('shows the fallback UI for render errors', () => {
    render(
      <ErrorBoundary>
        <Boom message="Cannot read properties of undefined (reading 'foo')" />
      </ErrorBoundary>,
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})

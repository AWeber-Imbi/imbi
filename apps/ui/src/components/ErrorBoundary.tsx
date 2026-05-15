import { Component, type ErrorInfo, type ReactNode } from 'react'

import { AlertCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

// Matches the various ways browsers report a failed dynamic `import()` for a
// hashed chunk that no longer exists on the server (typically after a redeploy
// while the user has a stale tab open). The MIME-type variant fires when the
// SPA's index.html is served as a fallback for the missing JS file.
const CHUNK_LOAD_ERROR_RE =
  /Loading chunk|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Expected a JavaScript-or-Wasm module/i

const RELOAD_GUARD_KEY = 'imbi:error-boundary-reloaded-at'
const RELOAD_GUARD_WINDOW_MS = 10_000

export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ErrorBoundary] Render error:', error, info)
    if (CHUNK_LOAD_ERROR_RE.test(error.message) && this.shouldAutoReload()) {
      window.sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
      window.location.reload()
    }
  }

  render(): ReactNode {
    const { error } = this.state
    if (error) {
      if (this.props.fallback) {
        return this.props.fallback(error, this.reset)
      }
      return (
        <div className="bg-secondary flex min-h-screen items-center justify-center p-4">
          <div
            aria-live="assertive"
            className="bg-primary text-primary w-full max-w-md rounded-lg border p-6 shadow-sm"
            role="alert"
          >
            <div className="flex items-center gap-3">
              <AlertCircle className="text-danger size-6 shrink-0" />
              <h1 className="text-lg font-semibold">Something went wrong</h1>
            </div>
            <p className="text-secondary mt-3 text-sm">
              An unexpected error occurred. Please try again.
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              <Button onClick={this.reset}>Try again</Button>
              <Button
                onClick={() => window.location.reload()}
                variant="outline"
              >
                Reload
              </Button>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }

  reset = (): void => {
    this.setState({ error: null })
  }

  private shouldAutoReload(): boolean {
    // Guard against infinite reload loops: only auto-reload if we haven't
    // already reloaded in the last RELOAD_GUARD_WINDOW_MS. If a fresh
    // index.html still references missing chunks the user falls through to
    // the manual fallback UI.
    try {
      const last = Number(
        window.sessionStorage.getItem(RELOAD_GUARD_KEY) ?? '0',
      )
      return Date.now() - last > RELOAD_GUARD_WINDOW_MS
    } catch {
      return false
    }
  }
}

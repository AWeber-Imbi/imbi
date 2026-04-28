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
  }

  render(): ReactNode {
    const { error } = this.state
    if (error) {
      if (this.props.fallback) {
        return this.props.fallback(error, this.reset)
      }
      return (
        <div className="flex min-h-screen items-center justify-center bg-secondary p-4">
          <div
            aria-live="assertive"
            className="w-full max-w-md rounded-lg border bg-primary p-6 text-primary shadow-sm"
            role="alert"
          >
            <div className="flex items-center gap-3">
              <AlertCircle className="h-6 w-6 flex-shrink-0 text-danger" />
              <h1 className="text-lg font-semibold">Something went wrong</h1>
            </div>
            <p className="mt-3 text-sm text-secondary">
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
}

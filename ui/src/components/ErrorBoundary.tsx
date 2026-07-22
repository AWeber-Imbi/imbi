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
}

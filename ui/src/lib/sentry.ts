import * as Sentry from '@sentry/react'

export function initSentry(): void {
  const dsn = resolveDsn()
  if (!dsn) return

  Sentry.init({
    dsn,
    integrations: [Sentry.browserTracingIntegration()],
    sendDefaultPii: false,
    tracesSampleRate: 0.1,
  })
}

function resolveDsn(): string | undefined {
  const runtime = window.__IMBI_SENTRY_DSN__
  if (runtime && !runtime.includes('{{')) {
    return runtime
  }
  return import.meta.env.VITE_SENTRY_DSN
}

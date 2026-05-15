import React from 'react'

import { BrowserRouter } from 'react-router-dom'

import { QueryClientProvider } from '@tanstack/react-query'
import ReactDOM from 'react-dom/client'

import { queryClient } from '@/lib/queryClient'
import { initSentry } from '@/lib/sentry'

import App from './App.tsx'
import './index.css'

initSentry()

// Vite emits `vite:preloadError` when a dynamic `import()` for a hashed chunk
// fails — typically when a redeploy has rotated the chunk hashes while the
// user has a stale tab open. Reload the SPA so the fresh index.html can fetch
// the new chunks. A short sessionStorage guard prevents an infinite reload
// loop if the freshly-loaded index.html still references missing chunks.
const RELOAD_GUARD_KEY = 'imbi:preload-error-reloaded-at'
const RELOAD_GUARD_WINDOW_MS = 10_000

function withinReloadGuardWindow(): boolean {
  try {
    const last = Number(window.sessionStorage.getItem(RELOAD_GUARD_KEY) ?? '0')
    return Date.now() - last <= RELOAD_GUARD_WINDOW_MS
  } catch {
    // If storage is unreadable we can't tell whether we just reloaded; treat
    // as in-window so we don't risk a loop.
    return true
  }
}

window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  if (withinReloadGuardWindow()) {
    return
  }
  try {
    window.sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
  } catch {
    // Storage write failures (quota, disabled, privacy mode) shouldn't block
    // recovery — fall through to the reload.
  }
  window.location.reload()
})

// Cache the root on the container so Vite HMR re-evaluating this module
// doesn't call createRoot() twice on the same node, which produces a
// React warning and a cascade of removeChild errors during dev reloads.
const container = document.getElementById('root')!
type ContainerWithRoot = HTMLElement & { __reactRoot?: ReactDOM.Root }
const node = container as ContainerWithRoot
const root = node.__reactRoot ?? ReactDOM.createRoot(node)
node.__reactRoot = root

root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)

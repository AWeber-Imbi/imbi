import { useEffect, useRef } from 'react'

// Diff two values via JSON.stringify. Good enough for form data (plain
// objects/arrays of primitives). Avoids pulling in a deep-equality dep.
function jsonEquals<T>(a: T, b: T): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/**
 * Destinations that MUST never be blocked by the unsaved-changes prompt. If
 * the session expires and auth code does `navigate('/login')`, a "Leave
 * anyway?" confirm would let a user cancel the redirect and remain on a
 * protected screen with no valid session. Auth redirects always win.
 */
const DEFAULT_BYPASS_PREFIXES = ['/login', '/auth/']

export interface UseDirtyStateOptions {
  /**
   * Pathname prefixes that bypass the confirm prompt. Defaults to auth paths
   * (`/login`, `/logout`, `/auth/`) so an expired session can always
   * redirect the user out. Matches both exact pathnames and any descendants
   * (e.g. `/login` also matches `/login?error=x`).
   */
  bypassPrefixes?: string[]
  /**
   * When false, the hook reports not-dirty and registers no listeners even if
   * the data differs. Useful to skip prompting during an in-flight save —
   * pass `enabled={!isSaving}` so the post-save `navigate()` doesn't prompt.
   * Defaults to true.
   */
  enabled?: boolean
  /**
   * Message shown in the in-app `window.confirm` prompt.
   * The browser native `beforeunload` prompt is not customizable; this only
   * affects the in-app navigation prompt.
   */
  message?: string
}

/**
 * Warns on unsaved-navigation while `initialData` differs from `currentData`.
 *
 * While dirty:
 * - Registers a `beforeunload` listener so tab-close/refresh surfaces the
 *   browser's native "Leave site?" prompt.
 * - Intercepts in-app navigation (history pushState/replaceState/popstate) and
 *   prompts via `window.confirm`. If the user cancels, the navigation is
 *   rolled back.
 *
 * NOTE: The in-app blocker uses history-patching rather than React Router's
 * `useBlocker` because the app mounts a `BrowserRouter` (not a data router);
 * `useBlocker` throws outside a data router. When the app migrates to
 * `createBrowserRouter` + `RouterProvider`, swap the history patch for
 * `useBlocker`.
 */
export function useDirtyState<T>(
  initialData: T,
  currentData: T,
  options: UseDirtyStateOptions = {},
): boolean {
  const enabled = options.enabled ?? true
  const isDirty = enabled && !jsonEquals(initialData, currentData)
  const message = options.message ?? 'You have unsaved changes. Leave anyway?'
  const bypassPrefixes = options.bypassPrefixes ?? DEFAULT_BYPASS_PREFIXES

  // Keep the latest message and bypass list in refs so effect deps stay stable.
  const messageRef = useRef(message)
  messageRef.current = message
  const bypassRef = useRef(bypassPrefixes)
  bypassRef.current = bypassPrefixes

  useEffect(() => {
    if (!isDirty) return

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      // Required for legacy Chrome compatibility.
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handleBeforeUnload)

    const originalPushState = window.history.pushState
    const originalReplaceState = window.history.replaceState

    const isBypassed = (url: null | string | undefined | URL): boolean =>
      matchesBypass(pathnameOf(url), bypassRef.current)
    const confirmNavigation = (): boolean => window.confirm(messageRef.current)

    const patchedPushState: typeof window.history.pushState = function (
      this: History,
      ...args
    ) {
      if (!isBypassed(args[2]) && !confirmNavigation()) return
      return originalPushState.apply(this, args)
    }

    const patchedReplaceState: typeof window.history.replaceState = function (
      this: History,
      ...args
    ) {
      if (!isBypassed(args[2]) && !confirmNavigation()) return
      return originalReplaceState.apply(this, args)
    }

    window.history.pushState = patchedPushState
    window.history.replaceState = patchedReplaceState

    // Capture the URL at activation so we can roll back popstate (back/forward)
    // if the user cancels.
    let lastHref = window.location.href

    const handlePopState = () => {
      const attemptedHref = window.location.href
      if (attemptedHref === lastHref) return
      if (isBypassed(attemptedHref) || confirmNavigation()) {
        lastHref = attemptedHref
        return
      }
      // Roll back: push the previous URL back into history.
      originalPushState.call(window.history, null, '', lastHref)
    }
    window.addEventListener('popstate', handlePopState)

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
      window.removeEventListener('popstate', handlePopState)
      window.history.pushState = originalPushState
      window.history.replaceState = originalReplaceState
    }
  }, [isDirty])

  return isDirty
}

function matchesBypass(pathname: null | string, prefixes: string[]): boolean {
  if (!pathname) return false
  return prefixes.some(
    (p) =>
      pathname === p ||
      pathname === p.replace(/\/$/, '') ||
      pathname.startsWith(p.endsWith('/') ? p : p + '/'),
  )
}

function pathnameOf(url: null | string | undefined | URL): null | string {
  if (url == null) return null
  if (typeof url !== 'string') return url.pathname
  // Relative path like "/login?error=x" — take up to the query/hash.
  if (url.startsWith('/')) return url.split(/[?#]/, 1)[0]
  // Absolute URL — parse via URL (resolves against current origin if needed).
  try {
    return new URL(url, window.location.origin).pathname
  } catch {
    return null
  }
}

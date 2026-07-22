/**
 * Post-login redirect handling, including the OAuth `return_to` used by the
 * MCP login flow.
 *
 * When an MCP client starts an OAuth login, the API's `/authorize` endpoint
 * bounces the browser here with `?return_to=<absolute /authorize URL>`. After
 * the user authenticates we must navigate back to that URL with a *full-page*
 * load (not a client-side route change) so the `SameSite=Strict` access
 * cookie is sent and `/authorize` can mint the authorization code.
 *
 * `return_to` is caller-controlled, so it is validated to prevent an open
 * redirect: only same-origin absolute URLs or root-relative paths are allowed.
 */

export function isSafeReturnTo(target: string): boolean {
  if (!target) return false
  // Root-relative path, but not a scheme-relative ("//host") or backslash trick.
  if (target.startsWith('/')) {
    return !target.startsWith('//') && !target.startsWith('/\\')
  }
  try {
    return new URL(target).origin === window.location.origin
  } catch {
    return false
  }
}

/**
 * Navigate to a validated post-login target. Absolute (same-origin) URLs use a
 * full-page load so cookies are sent to the API; relative paths stay in-SPA.
 */
export function performPostLoginRedirect(
  target: string,
  navigate: (to: string, opts?: { replace?: boolean }) => void,
): void {
  if (isAbsoluteUrl(target)) {
    window.location.assign(target)
  } else {
    navigate(target, { replace: true })
  }
}

/**
 * Resolve the best post-login destination from a `return_to` query param and
 * any stored redirect path, falling back to the dashboard.
 */
export function resolvePostLoginTarget(
  returnToParam: null | string,
  storedPath: null | string,
): string {
  for (const candidate of [returnToParam, storedPath]) {
    if (candidate && isSafeReturnTo(candidate)) return candidate
  }
  return '/dashboard'
}

function isAbsoluteUrl(target: string): boolean {
  return /^https?:\/\//i.test(target)
}

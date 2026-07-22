import { useAuthStore } from '@/stores/authStore'
import type { TokenResponse } from '@/types'

function resolveInjectedApiUrl(): string {
  // index.html injects `{{env "IMBI_API_URL"}}`; when served without a
  // templater (e.g. Vite dev) the placeholder reaches the browser literally,
  // so detect the unsubstituted form and fall back.
  const runtime = window.__IMBI_API_URL__
  if (runtime && !runtime.includes('{{')) {
    return runtime
  }
  return import.meta.env.VITE_API_URL
}

// The configured API URL as injected (absolute in deployment), with any
// trailing slash trimmed so the callback URLs built from it concatenate
// cleanly (e.g. `${API_URL}/auth/oauth/.../callback`). A slash-terminated
// IMBI_API_URL would otherwise yield a `//` that breaks exact OAuth redirect
// URI matching. Used to build the IdP callback URLs an admin registers with a
// provider.
export const API_URL = resolveInjectedApiUrl()?.replace(/\/+$/, '')
if (!API_URL) {
  throw new Error('IMBI_API_URL (or VITE_API_URL) is required')
}

// Base path for same-origin API requests. The SPA may be served from more
// than one host (e.g. an internal host plus a public host that fronts the
// MCP OAuth login), so requests must target the document's own origin
// rather than the injected host — otherwise a page served from the public
// host would call the unreachable internal API URL. We keep only the path
// of the injected (production) URL; the Vite-dev fallback is used verbatim
// so a cross-origin dev server still works.
function resolveApiBasePath(): string {
  const runtime = window.__IMBI_API_URL__
  if (runtime && !runtime.includes('{{')) {
    try {
      return new URL(runtime, window.location.origin).pathname.replace(
        /\/+$/,
        '',
      )
    } catch {
      return runtime
    }
  }
  return import.meta.env.VITE_API_URL
}

export const API_BASE_URL = resolveApiBasePath()

export const apiUrl = (path: string): string =>
  path.startsWith('/') ? `${API_BASE_URL}${path}` : `${API_BASE_URL}/${path}`

export class ApiError<T = unknown> extends Error {
  readonly data: T | undefined
  readonly response: { data: T | undefined; status: number; statusText: string }
  readonly status: number
  readonly statusText: string

  constructor(status: number, statusText: string, data?: T) {
    super(`HTTP ${status}: ${statusText}`)
    this.name = 'ApiError'
    this.status = status
    this.statusText = statusText
    this.data = data
    // Provide a response shape compatible with existing AxiosError usage
    this.response = { data, status, statusText }
  }
}

let refreshPromise: null | Promise<string> = null

async function refreshAccessToken(): Promise<string> {
  if (refreshPromise) {
    return refreshPromise
  }

  refreshPromise = (async () => {
    try {
      // The refresh token rides along as an HttpOnly cookie (C2), sent
      // automatically via credentials:'include'; no request body needed.
      const response = await fetch(`${API_BASE_URL}/auth/token/refresh`, {
        credentials: 'include',
        method: 'POST',
      })

      if (!response.ok) {
        throw new ApiError(response.status, response.statusText)
      }

      const { access_token } = (await response.json()) as TokenResponse
      useAuthStore.getState().setTokens(access_token)

      return access_token
    } catch (error) {
      console.error('[API] Token refresh failed:', error)
      useAuthStore.getState().clearTokens()
      throw error
    } finally {
      refreshPromise = null
    }
  })()

  return refreshPromise
}

const SKIP_AUTH_PATHS = [
  '/auth/login',
  '/auth/providers',
  '/auth/token/refresh',
  '/status',
]

class ApiClient {
  async delete<T>(url: string, signal?: AbortSignal): Promise<T> {
    return this.request<T>('DELETE', url, { signal })
  }

  async get<T>(
    url: string,
    params?: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<T> {
    return this.request<T>('GET', url, { params, signal })
  }

  async getWithHeaders<T>(
    url: string,
    params?: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<{ data: T; headers: Headers }> {
    const fullUrl = buildUrl(url, params)

    const response = await withAuthRetry(
      url,
      (token) => {
        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
        }
        if (token) {
          headers['Authorization'] = `Bearer ${token}`
        }

        return fetch(fullUrl, {
          credentials: 'include',
          headers,
          method: 'GET',
          signal,
        })
      },
      signal,
    )

    if (!response.ok) {
      let errorData: unknown
      try {
        errorData = await response.json()
      } catch {
        /* no body */
      }
      throw new ApiError(response.status, response.statusText, errorData)
    }

    const data = (await response.json()) as T
    return { data, headers: response.headers }
  }

  async patch<T>(
    url: string,
    data?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    return this.request<T>('PATCH', url, { body: data, signal })
  }

  async post<T>(url: string, data?: unknown, signal?: AbortSignal): Promise<T> {
    return this.request<T>('POST', url, { body: data, signal })
  }

  async postFormData<T>(
    url: string,
    formData: FormData,
    signal?: AbortSignal,
  ): Promise<T> {
    const response = await withAuthRetry(
      url,
      (token) => {
        const headers: Record<string, string> = {}
        if (token) {
          headers['Authorization'] = `Bearer ${token}`
        }

        // Don't set Content-Type — browser sets it with boundary for FormData
        return fetch(`${API_BASE_URL}${url}`, {
          body: formData,
          credentials: 'include',
          headers,
          method: 'POST',
          signal,
        })
      },
      signal,
    )

    return parseResponse<T>(response)
  }

  async put<T>(url: string, data?: unknown, signal?: AbortSignal): Promise<T> {
    return this.request<T>('PUT', url, { body: data, signal })
  }

  private async request<T>(
    method: string,
    url: string,
    options: {
      body?: unknown
      headers?: Record<string, string>
      params?: Record<string, unknown>
      signal?: AbortSignal
    } = {},
  ): Promise<T> {
    const { body, headers: extraHeaders, params, signal } = options
    const fullUrl = buildUrl(url, params)

    const response = await withAuthRetry(
      url,
      (token) => {
        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
          ...extraHeaders,
        }
        if (token) {
          headers['Authorization'] = `Bearer ${token}`
        }

        const init: RequestInit = {
          credentials: 'include',
          headers,
          method,
          signal,
        }

        if (body !== undefined) {
          init.body = JSON.stringify(body)
        }

        return fetch(fullUrl, init)
      },
      signal,
    )

    return parseResponse<T>(response)
  }
}

/**
 * Runs `fetcher` with an auth token resolved for `url`, and on a 401 response
 * performs one reactive refresh + retry. Handles the proactive-refresh check,
 * the `refreshPromise` lock (via `refreshAccessToken`), and the terminal
 * behavior when the refresh endpoint itself returns 401 (clear tokens +
 * redirect to login). URLs matching SKIP_AUTH_PATHS are passed a `null` token
 * and never retried.
 */
export async function withAuthRetry(
  url: string,
  fetcher: (token: null | string) => Promise<Response>,
  signal?: AbortSignal,
): Promise<Response> {
  const token = await resolveAuthToken(url)
  const response = await fetcher(token)

  if (response.status !== 401) return response
  if (shouldSkipAuth(url)) return response
  if (signal?.aborted) return response

  try {
    const newToken = await refreshAccessToken()
    return await fetcher(newToken)
  } catch (refreshError) {
    console.error(
      '[API] Token refresh failed, redirecting to login',
      refreshError,
    )
    // refreshAccessToken clears tokens in its catch block before rethrowing.
    redirectToLogin()
    return response
  }
}

function buildUrl(url: string, params?: Record<string, unknown>): string {
  let fullUrl = `${API_BASE_URL}${url}`
  if (params) {
    const searchParams = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null) continue
      // Arrays serialize as repeated query params (?k=a&k=b) so they
      // map cleanly to FastAPI ``list[str]`` query params.  String(arr)
      // would join with commas and produce a single key=a,b entry that
      // every list-based endpoint mis-parses as one element.
      if (Array.isArray(value)) {
        for (const item of value) {
          if (item !== undefined && item !== null) {
            searchParams.append(key, String(item))
          }
        }
      } else {
        searchParams.set(key, String(value))
      }
    }
    const qs = searchParams.toString()
    if (qs) fullUrl += `?${qs}`
  }
  return fullUrl
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorData: unknown
    try {
      errorData = await response.json()
    } catch {
      /* no body */
    }
    throw new ApiError(response.status, response.statusText, errorData)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function redirectToLogin(): void {
  const currentPath = window.location.pathname + window.location.search
  if (currentPath !== '/login') {
    sessionStorage.setItem('imbi_redirect_after_login', currentPath)
    window.location.href = '/login'
  }
}

async function resolveAuthToken(url: string): Promise<null | string> {
  if (shouldSkipAuth(url)) return null
  const authStore = useAuthStore.getState()
  if (authStore.isTokenExpired()) {
    try {
      return await refreshAccessToken()
    } catch (error) {
      // Proactive refresh failed; tokens already cleared by
      // refreshAccessToken. Redirect to login and surface the failure
      // rather than sending an unauthenticated request and triggering a
      // second refresh via the 401 handler.
      redirectToLogin()
      throw error instanceof ApiError
        ? error
        : new ApiError(401, 'Token refresh failed')
    }
  }
  return authStore.accessToken
}

function shouldSkipAuth(url: string): boolean {
  // Match the exact request path, not a substring: a substring check would
  // strip auth from any endpoint whose path merely contains a public one,
  // e.g. `/admin/dashboard/status` colliding with `/status`.
  const path = url.split(/[?#]/)[0]
  return SKIP_AUTH_PATHS.includes(path)
}

export const apiClient = new ApiClient()

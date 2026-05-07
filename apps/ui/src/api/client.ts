import { useAuthStore } from '@/stores/authStore'
import type { TokenResponse } from '@/types'

export const API_BASE_URL = import.meta.env.VITE_API_URL
if (!API_BASE_URL) {
  throw new Error('VITE_API_URL is required')
}

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
      const authStore = useAuthStore.getState()
      const currentRefreshToken = authStore.refreshToken

      if (!currentRefreshToken) {
        throw new Error('No refresh token available')
      }

      const response = await fetch(`${API_BASE_URL}/auth/token/refresh`, {
        body: JSON.stringify({ refresh_token: currentRefreshToken }),
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        method: 'POST',
      })

      if (!response.ok) {
        throw new ApiError(response.status, response.statusText)
      }

      const { access_token, refresh_token } =
        (await response.json()) as TokenResponse
      authStore.setTokens(access_token, refresh_token)

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
  return SKIP_AUTH_PATHS.some((path) => url.includes(path))
}

export const apiClient = new ApiClient()

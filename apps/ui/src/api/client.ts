import { useAuthStore } from '@/stores/authStore'
import type { TokenResponse } from '@/types'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'

console.log('API Base URL:', API_BASE_URL)
console.log('Using proxy with token:', !!import.meta.env.VITE_API_TOKEN)

export class ApiError<T = unknown> extends Error {
  readonly status: number
  readonly statusText: string
  readonly data: T | undefined
  readonly response: { status: number; statusText: string; data: T | undefined }

  constructor(status: number, statusText: string, data?: T) {
    super(`HTTP ${status}: ${statusText}`)
    this.name = 'ApiError'
    this.status = status
    this.statusText = statusText
    this.data = data
    // Provide a response shape compatible with existing AxiosError usage
    this.response = { status, statusText, data }
  }
}

let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  if (refreshPromise) {
    return refreshPromise
  }

  refreshPromise = (async () => {
    try {
      console.log('[API] Refreshing access token...')
      const authStore = useAuthStore.getState()
      const currentRefreshToken = authStore.refreshToken

      if (!currentRefreshToken) {
        throw new Error('No refresh token available')
      }

      const response = await fetch(`${API_BASE_URL}/auth/token/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: currentRefreshToken }),
      })

      if (!response.ok) {
        throw new ApiError(response.status, response.statusText)
      }

      const { access_token, refresh_token } =
        (await response.json()) as TokenResponse
      authStore.setTokens(access_token, refresh_token)
      console.log('[API] Access token refreshed successfully')

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

function shouldSkipAuth(url: string): boolean {
  return SKIP_AUTH_PATHS.some((path) => url.includes(path))
}

function redirectToLogin(): void {
  const currentPath = window.location.pathname + window.location.search
  if (currentPath !== '/login') {
    console.log('[API] Saving redirect path:', currentPath)
    sessionStorage.setItem('imbi_redirect_after_login', currentPath)
    console.log('[API] Redirecting to /login')
    window.location.href = '/login'
  }
}

class ApiClient {
  private async request<T>(
    method: string,
    url: string,
    options: {
      params?: Record<string, unknown>
      body?: unknown
      headers?: Record<string, string>
      isRetry?: boolean
    } = {},
  ): Promise<T> {
    const { params, body, headers: extraHeaders, isRetry } = options

    let fullUrl = `${API_BASE_URL}${url}`
    if (params) {
      const searchParams = new URLSearchParams()
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null) {
          searchParams.set(key, String(value))
        }
      }
      const qs = searchParams.toString()
      if (qs) fullUrl += `?${qs}`
    }

    console.log(`[API] ${method} ${url}`)

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...extraHeaders,
    }

    // Add auth token unless this is an auth endpoint
    if (!shouldSkipAuth(url)) {
      const authStore = useAuthStore.getState()
      let token = authStore.accessToken

      console.log('[API] Request state:', {
        hasToken: !!token,
        hasRefreshToken: !!authStore.refreshToken,
        isExpired: authStore.isTokenExpired(),
      })

      if (authStore.isTokenExpired()) {
        console.log('[API] Token expired, refreshing...')
        try {
          token = await refreshAccessToken()
        } catch (_error) {
          console.error('[API] Token refresh failed, proceeding without token')
        }
      }

      if (token) {
        headers['Authorization'] = `Bearer ${token}`
        console.log('[API] Added Authorization header')
      } else {
        console.warn('[API] No token available for request')
      }
    }

    const init: RequestInit = {
      method,
      credentials: 'include',
      headers,
    }

    if (body !== undefined) {
      init.body = JSON.stringify(body)
    }

    const response = await fetch(fullUrl, init)

    console.log(`[API] Response ${response.status} for ${url}`)

    if (!response.ok) {
      let errorData: unknown
      try {
        errorData = await response.json()
      } catch {
        // No JSON body in error response
      }

      // Handle 401 with token refresh retry
      if (response.status === 401 && !isRetry) {
        console.log('[API] Got 401, attempting token refresh...')

        // Don't refresh if this IS the refresh request
        if (url.includes('/auth/token/refresh')) {
          console.error(
            '[API] Refresh token request failed, clearing tokens and redirecting',
          )
          useAuthStore.getState().clearTokens()
          redirectToLogin()
          throw new ApiError(response.status, response.statusText, errorData)
        }

        try {
          await refreshAccessToken()
          console.log(
            '[API] Token refresh successful, retrying original request',
          )
          return this.request<T>(method, url, { ...options, isRetry: true })
        } catch (refreshError) {
          console.error(
            '[API] Token refresh failed, redirecting to login',
            refreshError,
          )
          useAuthStore.getState().clearTokens()
          redirectToLogin()
          throw new ApiError(response.status, response.statusText, errorData)
        }
      }

      throw new ApiError(response.status, response.statusText, errorData)
    }

    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  async get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
    return this.request<T>('GET', url, { params })
  }

  async post<T>(url: string, data?: unknown): Promise<T> {
    return this.request<T>('POST', url, { body: data })
  }

  async put<T>(url: string, data?: unknown): Promise<T> {
    return this.request<T>('PUT', url, { body: data })
  }

  async patch<T>(url: string, data?: unknown): Promise<T> {
    return this.request<T>('PATCH', url, { body: data })
  }

  async delete<T>(url: string): Promise<T> {
    return this.request<T>('DELETE', url)
  }

  async postFormData<T>(url: string, formData: FormData): Promise<T> {
    const authStore = useAuthStore.getState()
    let token = authStore.accessToken

    if (authStore.isTokenExpired()) {
      try {
        token = await refreshAccessToken()
      } catch {
        // proceed without token
      }
    }

    const headers: Record<string, string> = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    // Don't set Content-Type — browser sets it with boundary for FormData
    const response = await fetch(`${API_BASE_URL}${url}`, {
      method: 'POST',
      credentials: 'include',
      headers,
      body: formData,
    })

    if (!response.ok) {
      let errorData: unknown
      try {
        errorData = await response.json()
      } catch {
        // No JSON body
      }
      throw new ApiError(response.status, response.statusText, errorData)
    }

    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  async getWithHeaders<T>(
    url: string,
    params?: Record<string, unknown>,
  ): Promise<{ data: T; headers: Headers }> {
    let fullUrl = `${API_BASE_URL}${url}`
    if (params) {
      const searchParams = new URLSearchParams()
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null) {
          searchParams.set(key, String(value))
        }
      }
      const qs = searchParams.toString()
      if (qs) fullUrl += `?${qs}`
    }

    const authStore = useAuthStore.getState()
    let token = authStore.accessToken

    if (authStore.isTokenExpired()) {
      try {
        token = await refreshAccessToken()
      } catch {
        // proceed without token
      }
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    const response = await fetch(fullUrl, {
      method: 'GET',
      credentials: 'include',
      headers,
    })

    if (!response.ok) {
      let errorData: unknown
      try {
        errorData = await response.json()
      } catch {
        // No JSON body
      }
      throw new ApiError(response.status, response.statusText, errorData)
    }

    const data = (await response.json()) as T
    return { data, headers: response.headers }
  }
}

export const apiClient = new ApiClient()

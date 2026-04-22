import { useAuthStore } from '@/stores/authStore'
import type { TokenResponse } from '@/types'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'

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
    sessionStorage.setItem('imbi_redirect_after_login', currentPath)
    window.location.href = '/login'
  }
}

function buildUrl(url: string, params?: Record<string, unknown>): string {
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
  return fullUrl
}

class ApiClient {
  private async resolveAuthToken(url: string): Promise<string | null> {
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

  private async handleResponse<T>(
    response: Response,
    retryRequest: () => Promise<T>,
    isRetry: boolean,
    url: string,
  ): Promise<T> {
    if (!response.ok) {
      let errorData: unknown
      try {
        errorData = await response.json()
      } catch {
        /* no body */
      }

      if (response.status === 401 && !isRetry) {
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
          return await retryRequest()
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
    const { params, body, headers: extraHeaders, isRetry = false } = options

    const fullUrl = buildUrl(url, params)

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...extraHeaders,
    }

    const token = await this.resolveAuthToken(url)
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
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

    return this.handleResponse<T>(
      response,
      () => this.request<T>(method, url, { ...options, isRetry: true }),
      isRetry,
      url,
    )
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

  async postFormData<T>(
    url: string,
    formData: FormData,
    isRetry = false,
  ): Promise<T> {
    const headers: Record<string, string> = {}
    const token = await this.resolveAuthToken(url)
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

    return this.handleResponse<T>(
      response,
      () => this.postFormData<T>(url, formData, true),
      isRetry,
      url,
    )
  }

  async getWithHeaders<T>(
    url: string,
    params?: Record<string, unknown>,
    isRetry = false,
  ): Promise<{ data: T; headers: Headers }> {
    const fullUrl = buildUrl(url, params)

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    const token = await this.resolveAuthToken(url)
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
        /* no body */
      }

      if (response.status === 401 && !isRetry) {
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
          return await this.getWithHeaders<T>(url, params, true)
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

    const data = (await response.json()) as T
    return { data, headers: response.headers }
  }
}

export const apiClient = new ApiClient()

import axios, { AxiosError, AxiosInstance } from 'axios'
import { useAuthStore } from '@/stores/authStore'
import type { TokenResponse } from '@/types'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'

console.log('API Base URL:', API_BASE_URL)
console.log('Using proxy with token:', !!import.meta.env.VITE_API_TOKEN)

let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(client: AxiosInstance): Promise<string> {
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

      const response = await client.post<TokenResponse>('/auth/token/refresh', {
        refresh_token: currentRefreshToken
      })
      const { access_token, refresh_token } = response.data

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

class ApiClient {
  private client: AxiosInstance

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      withCredentials: true,
      headers: {
        'Content-Type': 'application/json',
      },
    })

    this.client.interceptors.request.use(
      async (config) => {
        console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`)

        if (config.url?.includes('/auth/login') ||
            config.url?.includes('/auth/providers') ||
            config.url?.includes('/auth/token/refresh') ||
            config.url?.includes('/status')) {
          return config
        }

        const authStore = useAuthStore.getState()
        let token = authStore.accessToken

        console.log('[API] Request interceptor state:', {
          hasToken: !!token,
          hasRefreshToken: !!authStore.refreshToken,
          isExpired: authStore.isTokenExpired()
        })

        if (authStore.isTokenExpired()) {
          console.log('[API] Token expired, refreshing...')
          try {
            token = await refreshAccessToken(this.client)
          } catch (error) {
            console.error('[API] Token refresh failed, proceeding without token')
          }
        }

        if (token) {
          config.headers.Authorization = `Bearer ${token}`
          console.log('[API] Added Authorization header')
        } else {
          console.warn('[API] No token available for request')
        }

        return config
      },
      (error) => Promise.reject(error)
    )

    this.client.interceptors.response.use(
      (response) => {
        console.log(`[API] Response ${response.status} for ${response.config.url}`)
        return response
      },
      async (error: AxiosError) => {
        console.error(`[API] Error ${error.response?.status || 'network'} for ${error.config?.url}:`, error.message)

        const originalRequest = error.config as any

        if (error.response?.status === 401 && !originalRequest._retry) {
          console.log('[API] Got 401, attempting token refresh...')
          originalRequest._retry = true

          // Don't try to refresh if this IS the refresh request
          if (originalRequest.url?.includes('/auth/token/refresh')) {
            console.error('[API] Refresh token request failed, clearing tokens and redirecting')
            useAuthStore.getState().clearTokens()

            const currentPath = window.location.pathname + window.location.search
            if (currentPath !== '/login') {
              console.log('[API] Saving redirect path:', currentPath)
              sessionStorage.setItem('imbi_redirect_after_login', currentPath)
              console.log('[API] Redirecting to /login')
              window.location.href = '/login'
            }
            return Promise.reject(error)
          }

          try {
            const newToken = await refreshAccessToken(this.client)
            console.log('[API] Token refresh successful, retrying original request')

            originalRequest.headers.Authorization = `Bearer ${newToken}`
            return this.client(originalRequest)
          } catch (refreshError) {
            console.error('[API] Token refresh failed, redirecting to login', refreshError)
            useAuthStore.getState().clearTokens()

            // Save current path to redirect back after login
            const currentPath = window.location.pathname + window.location.search
            if (currentPath !== '/login') {
              console.log('[API] Saving redirect path:', currentPath)
              sessionStorage.setItem('imbi_redirect_after_login', currentPath)
              console.log('[API] Redirecting to /login')
              window.location.href = '/login'
            }
            return Promise.reject(refreshError)
          }
        }

        return Promise.reject(error)
      }
    )
  }

  async get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
    const response = await this.client.get<T>(url, { params })
    return response.data
  }

  async post<T>(url: string, data?: unknown): Promise<T> {
    const response = await this.client.post<T>(url, data)
    return response.data
  }

  async put<T>(url: string, data?: unknown): Promise<T> {
    const response = await this.client.put<T>(url, data)
    return response.data
  }

  async patch<T>(url: string, data?: unknown): Promise<T> {
    const response = await this.client.patch<T>(url, data)
    return response.data
  }

  async delete<T>(url: string): Promise<T> {
    const response = await this.client.delete<T>(url)
    return response.data
  }

  async postFormData<T>(url: string, formData: FormData): Promise<T> {
    const response = await this.client.post<T>(url, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return response.data
  }
}

export const apiClient = new ApiClient()

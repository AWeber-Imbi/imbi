import axios, { AxiosError, AxiosInstance } from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'

console.log('API Base URL:', API_BASE_URL)
console.log('Using proxy with token:', !!import.meta.env.VITE_API_TOKEN)

class ApiClient {
  private client: AxiosInstance

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      withCredentials: true, // For session cookie auth when available
      headers: {
        'Content-Type': 'application/json',
      },
    })

    // Request interceptor - no need to add token here, proxy handles it
    this.client.interceptors.request.use(
      (config) => {
        console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`)
        return config
      },
      (error) => Promise.reject(error)
    )

    // Response interceptor for handling errors
    this.client.interceptors.response.use(
      (response) => {
        console.log(`[API] Response ${response.status} for ${response.config.url}`)
        return response
      },
      (error: AxiosError) => {
        console.error(`[API] Error ${error.response?.status || 'network'} for ${error.config?.url}:`, error.message)
        if (error.response?.status === 401) {
          // For development with API token, this shouldn't happen
          // For production, redirect to login
          console.error('Authentication failed - check your API token in .env')
        }
        return Promise.reject(error)
      }
    )
  }

  // Generic methods
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
}

export const apiClient = new ApiClient()

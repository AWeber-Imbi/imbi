import { create } from 'zustand'
import { jwtDecode } from 'jwt-decode'

interface JwtPayload {
  sub: string
  exp: number
  iat: number
}

interface AuthStore {
  accessToken: string | null
  tokenExpiry: number | null

  setAccessToken: (token: string) => void
  clearTokens: () => void
  isTokenExpired: () => boolean
  getUsername: () => string | null
}

export const useAuthStore = create<AuthStore>((set, get) => ({
  accessToken: null,
  tokenExpiry: null,

  setAccessToken: (token: string) => {
    try {
      const decoded = jwtDecode<JwtPayload>(token)
      set({
        accessToken: token,
        tokenExpiry: decoded.exp * 1000
      })
    } catch (error) {
      console.error('[Auth] Failed to decode JWT:', error)
      set({ accessToken: null, tokenExpiry: null })
    }
  },

  clearTokens: () => {
    set({ accessToken: null, tokenExpiry: null })
  },

  isTokenExpired: () => {
    const { tokenExpiry } = get()
    if (!tokenExpiry) return true
    return Date.now() > (tokenExpiry - 5 * 60 * 1000)
  },

  getUsername: () => {
    const { accessToken } = get()
    if (!accessToken) return null
    try {
      const decoded = jwtDecode<JwtPayload>(accessToken)
      return decoded.sub
    } catch {
      return null
    }
  }
}))

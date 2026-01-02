import { create } from 'zustand'
import { jwtDecode } from 'jwt-decode'

interface JwtPayload {
  sub: string
  exp: number
  iat: number
}

interface AuthStore {
  accessToken: string | null
  refreshToken: string | null
  tokenExpiry: number | null

  setTokens: (accessToken: string, refreshToken: string) => void
  setAccessToken: (token: string) => void
  clearTokens: () => void
  isTokenExpired: () => boolean
  getUsername: () => string | null
}

export const useAuthStore = create<AuthStore>((set, get) => ({
  accessToken: null,
  refreshToken: null,
  tokenExpiry: null,

  setTokens: (accessToken: string, refreshToken: string) => {
    try {
      const decoded = jwtDecode<JwtPayload>(accessToken)
      const tokenExpiry = decoded.exp * 1000
      console.log('[AuthStore] Setting tokens:', {
        username: decoded.sub,
        expiresAt: new Date(tokenExpiry).toISOString(),
        expiresIn: Math.round((tokenExpiry - Date.now()) / 1000) + 's',
        now: new Date().toISOString()
      })
      set({
        accessToken,
        refreshToken,
        tokenExpiry
      })
    } catch (error) {
      console.error('[Auth] Failed to decode JWT:', error)
      set({ accessToken: null, refreshToken: null, tokenExpiry: null })
    }
  },

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
    set({ accessToken: null, refreshToken: null, tokenExpiry: null })
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
      console.log('[AuthStore] Decoded JWT payload:', decoded)
      console.log('[AuthStore] JWT sub field:', decoded.sub)
      return decoded.sub
    } catch {
      return null
    }
  }
}))

import { jwtDecode } from 'jwt-decode'
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthStore {
  accessToken: null | string
  clearTokens: () => void
  getUsername: () => null | string

  isTokenExpired: () => boolean
  setAccessToken: (token: string) => void
  setTokens: (accessToken: string) => void
  tokenExpiry: null | number
}

interface JwtPayload {
  exp: number
  iat: number
  sub: string
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      accessToken: null,
      clearTokens: () => {
        set({ accessToken: null, tokenExpiry: null })
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
      },

      isTokenExpired: () => {
        const { tokenExpiry } = get()
        if (!tokenExpiry) return true
        return Date.now() > tokenExpiry - 5 * 60 * 1000
      },

      setAccessToken: (token: string) => {
        try {
          const decoded = jwtDecode<JwtPayload>(token)
          set({
            accessToken: token,
            tokenExpiry: decoded.exp * 1000,
          })
        } catch {
          set({ accessToken: null, tokenExpiry: null })
        }
      },

      setTokens: (accessToken: string) => {
        try {
          const decoded = jwtDecode<JwtPayload>(accessToken)
          const tokenExpiry = decoded.exp * 1000
          set({
            accessToken,
            tokenExpiry,
          })
        } catch {
          set({ accessToken: null, tokenExpiry: null })
        }
      },

      tokenExpiry: null,
    }),
    {
      name: 'imbi-auth-storage',
    },
  ),
)

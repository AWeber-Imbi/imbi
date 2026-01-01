import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore } from './authStore'

describe('authStore', () => {
  beforeEach(() => {
    useAuthStore.getState().clearTokens()
  })

  describe('setAccessToken', () => {
    it('should decode and store a valid JWT token', () => {
      const validToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiZXhwIjoxNzM1NzQ3MjAwLCJpYXQiOjE3MzU3NDcyMDB9.test'

      useAuthStore.getState().setAccessToken(validToken)

      const state = useAuthStore.getState()
      expect(state.accessToken).toBe(validToken)
      expect(state.tokenExpiry).toBe(1735747200000)
    })

    it('should clear token on invalid JWT', () => {
      const invalidToken = 'invalid.token.here'

      useAuthStore.getState().setAccessToken(invalidToken)

      const state = useAuthStore.getState()
      expect(state.accessToken).toBeNull()
      expect(state.tokenExpiry).toBeNull()
    })
  })

  describe('clearTokens', () => {
    it('should clear all token data', () => {
      const validToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiZXhwIjoxNzM1NzQ3MjAwLCJpYXQiOjE3MzU3NDcyMDB9.test'
      useAuthStore.getState().setAccessToken(validToken)

      useAuthStore.getState().clearTokens()

      const state = useAuthStore.getState()
      expect(state.accessToken).toBeNull()
      expect(state.tokenExpiry).toBeNull()
    })
  })

  describe('isTokenExpired', () => {
    it('should return true if no token exists', () => {
      const isExpired = useAuthStore.getState().isTokenExpired()
      expect(isExpired).toBe(true)
    })

    it('should return true if token expiry is in the past', () => {
      const expiredToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiZXhwIjoxNjAwMDAwMDAwLCJpYXQiOjE2MDAwMDAwMDB9.test'

      useAuthStore.getState().setAccessToken(expiredToken)

      const isExpired = useAuthStore.getState().isTokenExpired()
      expect(isExpired).toBe(true)
    })

    it('should return false if token is valid and not expiring soon', () => {
      const futureTimestamp = Math.floor(Date.now() / 1000) + 3600
      const futureToken = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiZXhwIjoke2Z1dHVyZVRpbWVzdGFtcH0sImlhdCI6MTYwMDAwMDAwMH0.test`

      useAuthStore.setState({
        accessToken: futureToken,
        tokenExpiry: futureTimestamp * 1000
      })

      const isExpired = useAuthStore.getState().isTokenExpired()
      expect(isExpired).toBe(false)
    })

    it('should return true if token expires within 5 minutes', () => {
      const soonTimestamp = Math.floor(Date.now() / 1000) + 240

      useAuthStore.setState({
        accessToken: 'token',
        tokenExpiry: soonTimestamp * 1000
      })

      const isExpired = useAuthStore.getState().isTokenExpired()
      expect(isExpired).toBe(true)
    })
  })

  describe('getUsername', () => {
    it('should return null if no token exists', () => {
      const username = useAuthStore.getState().getUsername()
      expect(username).toBeNull()
    })

    it('should extract username from valid JWT', () => {
      const validToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiZXhwIjoxNzM1NzQ3MjAwLCJpYXQiOjE3MzU3NDcyMDB9.test'

      useAuthStore.getState().setAccessToken(validToken)

      const username = useAuthStore.getState().getUsername()
      expect(username).toBe('test@example.com')
    })

    it('should return null for invalid JWT', () => {
      useAuthStore.setState({ accessToken: 'invalid.token' })

      const username = useAuthStore.getState().getUsername()
      expect(username).toBeNull()
    })
  })
})

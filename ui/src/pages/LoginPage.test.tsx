import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { render, screen, waitFor } from '@/test/utils'

import { LoginPage } from './LoginPage'

const login = vi.fn()

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    isLoading: false,
    login,
    loginWithOAuth: vi.fn(),
  }),
}))

vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  getAuthProviders: vi.fn().mockResolvedValue({
    default_redirect: '/',
    providers: [{ enabled: true, id: 'password', type: 'password' }],
  }),
}))

const signIn = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.type(
    await screen.findByLabelText(/email address/i),
    'a@example.com',
  )
  await user.type(screen.getByLabelText(/^password$/i), 'secret-password')
  await user.click(screen.getByRole('button', { name: /sign in/i }))
}

describe('LoginPage MFA step', () => {
  beforeEach(() => {
    login.mockReset()
  })

  it('asks for a code and resends the login with mfa_code', async () => {
    login
      .mockRejectedValueOnce(
        new ApiError(401, 'Unauthorized', { detail: 'MFA code required' }),
      )
      .mockResolvedValueOnce(undefined)
    const user = userEvent.setup()
    render(<LoginPage />)

    await signIn(user)
    await user.type(
      await screen.findByLabelText(/authentication code/i),
      'abcd1234',
    )
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => expect(login).toHaveBeenCalledTimes(2))
    expect(login).toHaveBeenLastCalledWith({
      email: 'a@example.com',
      mfa_code: 'abcd1234',
      password: 'secret-password',
    })
  })

  it('shows the error for a wrong code and keeps the MFA step', async () => {
    login
      .mockRejectedValueOnce(
        new ApiError(401, 'Unauthorized', { detail: 'MFA code required' }),
      )
      .mockRejectedValueOnce(
        new ApiError(401, 'Unauthorized', { detail: 'Invalid MFA code' }),
      )
    const user = userEvent.setup()
    render(<LoginPage />)

    await signIn(user)
    await user.type(
      await screen.findByLabelText(/authentication code/i),
      '000000',
    )
    await user.click(screen.getByRole('button', { name: /verify/i }))

    expect(await screen.findByText('Invalid MFA code')).toBeInTheDocument()
    expect(screen.getByLabelText(/authentication code/i)).toBeInTheDocument()
  })

  it('goes back to the password form', async () => {
    login.mockRejectedValueOnce(
      new ApiError(401, 'Unauthorized', { detail: 'MFA code required' }),
    )
    const user = userEvent.setup()
    render(<LoginPage />)

    await signIn(user)
    await user.click(await screen.findByRole('button', { name: /back/i }))

    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument()
  })
})

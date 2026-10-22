import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { disableMfa, getMfaStatus, setupMfa, verifyMfa } from '@/api/endpoints'
import { render, screen, waitFor } from '@/test/utils'

import { SettingsSecurity } from './SettingsSecurity'

vi.mock('@/api/endpoints', () => ({
  disableMfa: vi.fn(),
  getMfaStatus: vi.fn(),
  setupMfa: vi.fn(),
  verifyMfa: vi.fn(),
}))

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

describe('SettingsSecurity two-factor authentication', () => {
  beforeEach(() => {
    vi.mocked(disableMfa).mockReset()
    vi.mocked(getMfaStatus).mockReset()
    vi.mocked(setupMfa).mockReset()
    vi.mocked(verifyMfa).mockReset()
  })

  it('enrolls: shows the secret and backup codes, then verifies', async () => {
    vi.mocked(getMfaStatus).mockResolvedValue({
      backup_codes_remaining: 0,
      enabled: false,
      has_password: true,
    })
    vi.mocked(setupMfa).mockResolvedValue({
      backup_codes: ['aaaa1111', 'bbbb2222'],
      provisioning_uri: 'otpauth://totp/x',
      qr_code: 'iVBORw0KGgo=',
      secret: 'JBSWY3DPEHPK3PXP',
    })
    vi.mocked(verifyMfa).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<SettingsSecurity />)

    await user.click(await screen.findByRole('button', { name: /set up/i }))

    expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    expect(screen.getByText('aaaa1111')).toBeInTheDocument()
    expect(screen.getByAltText(/qr code/i)).toHaveAttribute(
      'src',
      'data:image/png;base64,iVBORw0KGgo=',
    )

    await user.type(screen.getByLabelText(/code from the app/i), '123456')
    await user.click(screen.getByRole('button', { name: /turn on/i }))

    await waitFor(() => expect(verifyMfa).toHaveBeenCalledWith('123456'))
  })

  it('turns MFA off with the password for a password user', async () => {
    vi.mocked(getMfaStatus).mockResolvedValue({
      backup_codes_remaining: 7,
      enabled: true,
      has_password: true,
    })
    vi.mocked(disableMfa).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<SettingsSecurity />)

    expect(await screen.findByText('7 backup codes left')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /turn off/i }))
    await user.type(screen.getByLabelText(/enter your password/i), 'pw')
    await user.click(screen.getByRole('button', { name: /turn off/i }))

    await waitFor(() =>
      expect(disableMfa).toHaveBeenCalledWith({ current_password: 'pw' }),
    )
  })

  it('asks an OAuth-only user for a code to turn MFA off', async () => {
    vi.mocked(getMfaStatus).mockResolvedValue({
      backup_codes_remaining: 7,
      enabled: true,
      has_password: false,
    })
    vi.mocked(disableMfa).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<SettingsSecurity />)

    await user.click(await screen.findByRole('button', { name: /turn off/i }))
    await user.type(screen.getByLabelText(/authenticator app/i), '654321')
    await user.click(screen.getByRole('button', { name: /turn off/i }))

    await waitFor(() =>
      expect(disableMfa).toHaveBeenCalledWith({ mfa_code: '654321' }),
    )
  })
})

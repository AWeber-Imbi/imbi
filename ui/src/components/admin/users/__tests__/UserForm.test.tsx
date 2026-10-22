import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'
import type { AdminUser } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getLocalAuthConfig: vi.fn(() => Promise.resolve({ enabled: true })),
  getRoles: vi.fn(() => Promise.resolve([])),
  resetUserMfa: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ organizations: [] }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { email: 'admin@example.com' } }),
}))

const { UserForm } = await import('../UserForm')

const baseUser: AdminUser = {
  created_at: '2026-01-01T00:00:00Z',
  display_name: 'Someone',
  email: 'someone@example.com',
  email_notifications: true,
  is_active: true,
  is_admin: false,
  is_service_account: false,
  roles: [],
}

function renderForm(user: AdminUser) {
  render(<UserForm onCancel={vi.fn()} onSave={vi.fn()} user={user} />)
}

describe('UserForm Reset MFA', () => {
  it('offers Reset MFA for another user', async () => {
    renderForm(baseUser)
    expect(
      await screen.findByRole('button', { name: /reset mfa/i }),
    ).toBeInTheDocument()
  })

  it('hides Reset MFA on the caller’s own account', async () => {
    renderForm({ ...baseUser, email: 'admin@example.com' })
    expect(
      await screen.findByText(/use settings > security/i),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reset mfa/i })).toBeNull()
  })
})

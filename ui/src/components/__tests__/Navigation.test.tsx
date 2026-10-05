import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({
    organizations: [{ name: 'Acme', slug: 'acme' }],
    selectedOrganization: { name: 'Acme', slug: 'acme' },
    setSelectedOrganization: vi.fn(),
  }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false, toggleTheme: vi.fn() }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    logout: vi.fn(),
    user: {
      display_name: 'Admin',
      email: 'admin@example.com',
      is_admin: true,
      permissions: ['prompt:read'],
    },
  }),
}))

describe('Navigation', () => {
  it('has no Prompts item; prompts live in Admin and the Assistant', async () => {
    const { Navigation } = await import('../Navigation')
    render(<Navigation />)
    expect(screen.getByText('Projects')).toBeInTheDocument()
    expect(screen.getByText('Admin')).toBeInTheDocument()
    expect(screen.queryByText('Prompts')).not.toBeInTheDocument()
  })
})

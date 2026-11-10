import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'

const auth = vi.hoisted(() => ({
  user: {
    display_name: 'Admin',
    email: 'admin@example.com',
    is_admin: true,
    organizations: [] as {
      organization_slug: string
      permissions: string[]
    }[],
    permissions: ['prompt:read'],
  },
}))

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
  useAuth: () => ({ logout: vi.fn(), user: auth.user }),
}))

describe('Navigation', () => {
  it('has no Prompts item; prompts live in Admin and the Assistant', async () => {
    const { Navigation } = await import('../Navigation')
    render(<Navigation />)
    expect(screen.getByText('Projects')).toBeInTheDocument()
    expect(screen.getByText('Admin')).toBeInTheDocument()
    expect(screen.queryByText('Prompts')).not.toBeInTheDocument()
  })

  it('shows the Agents menu to a runner reader without agent:read', async () => {
    auth.user = {
      ...auth.user,
      is_admin: false,
      organizations: [
        { organization_slug: 'acme', permissions: ['harness_pool:read'] },
      ],
      permissions: ['harness_pool:read'],
    }
    const { Navigation } = await import('../Navigation')
    render(<Navigation />)
    expect(screen.getByText('Agents')).toBeInTheDocument()
    expect(screen.queryByText('Admin')).not.toBeInTheDocument()
  })
})

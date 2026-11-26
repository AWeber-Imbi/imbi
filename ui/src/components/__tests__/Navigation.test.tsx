import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'

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
  useOptionalOrganization: () => null,
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
    expect(screen.queryByText('Admin')).not.toBeInTheDocument()
    const agents = screen.getByRole('link', { name: /Agents/ })
    expect(agents).toHaveAttribute('href', '/agents/dashboard')
    await userEvent.hover(agents)
    expect(
      await screen.findByRole('menuitem', { name: /Runners/ }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('menuitem', { name: /Dashboard/ }),
    ).not.toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await waitFor(() =>
      expect(screen.queryByRole('menuitem')).not.toBeInTheDocument(),
    )
    agents.focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(
      await screen.findByRole('menuitem', { name: /Runners/ }),
    ).toBeInTheDocument()
  })

  it('keeps focus where it is when hover opens the Agents menu', async () => {
    const { Navigation } = await import('../Navigation')
    render(
      <>
        <input aria-label="Scratch input" />
        <Navigation />
      </>,
    )
    const input = screen.getByRole('textbox', { name: 'Scratch input' })
    input.focus()
    await userEvent.hover(screen.getByRole('link', { name: /Agents/ }))
    await screen.findByRole('menuitem', { name: /Runners/ })
    expect(input).toHaveFocus()
  })

  it('moves focus into a hover-opened Agents menu on ArrowDown', async () => {
    const { Navigation } = await import('../Navigation')
    render(<Navigation />)
    const agents = screen.getByRole('link', { name: /Agents/ })
    await userEvent.hover(agents)
    await screen.findByRole('menuitem', { name: /Runners/ })
    agents.focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getAllByRole('menuitem')[0]).toHaveFocus()
  })

  it('keeps the Agents menu open on ArrowDown after the pointer leaves', async () => {
    const { Navigation } = await import('../Navigation')
    render(<Navigation />)
    const agents = screen.getByRole('link', { name: /Agents/ })
    await userEvent.hover(agents)
    await screen.findByRole('menuitem', { name: /Runners/ })
    await userEvent.unhover(agents)
    agents.focus()
    await userEvent.keyboard('{ArrowDown}')
    await new Promise((resolve) => setTimeout(resolve, 150))
    expect(screen.getAllByRole('menuitem')[0]).toHaveFocus()
  })

  it('keeps a keyboard-opened Agents menu open when the pointer leaves', async () => {
    const { Navigation } = await import('../Navigation')
    render(<Navigation />)
    const agents = screen.getByRole('link', { name: /Agents/ })
    agents.focus()
    await userEvent.keyboard('{ArrowDown}')
    await screen.findByRole('menuitem', { name: /Runners/ })
    await userEvent.hover(agents)
    await userEvent.unhover(agents)
    await new Promise((resolve) => setTimeout(resolve, 150))
    expect(screen.getAllByRole('menuitem')[0]).toHaveFocus()
  })
})

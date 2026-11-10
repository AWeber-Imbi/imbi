import { Route, Routes } from 'react-router-dom'

import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'

import { Admin } from '../Admin'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { name: 'Acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('../admin/AdminOverview', () => ({
  AdminOverview: () => <div>overview</div>,
}))

function renderAt(path: string) {
  window.history.pushState({}, '', path)
  render(
    <Routes>
      <Route element={<Admin />} path="/admin/:section?/:slug?/:action?" />
      <Route element={<div>agents</div>} path="/agents/*" />
    </Routes>,
  )
}

describe('Admin', () => {
  it('sends a moved section to its Agents page', async () => {
    renderAt('/admin/egress-destinations/pg-main/edit')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/agents/egress/pg-main/edit'),
    )
  })

  it('shows the sections under their groups', () => {
    renderAt('/admin/overview')
    const nav = screen.getByRole('navigation')
    for (const text of ['Catalog', 'Connections', 'Access', 'AI', 'System']) {
      expect(nav).toHaveTextContent(text)
    }
    expect(nav).not.toHaveTextContent('Agent Runners')
  })
})

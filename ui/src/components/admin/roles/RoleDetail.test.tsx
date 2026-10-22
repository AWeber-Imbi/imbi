import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'

import { RoleDetail } from './RoleDetail'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getAdminSettings: vi.fn().mockResolvedValue({ permissions: [] }),
  getRole: vi.fn().mockResolvedValue({
    is_system: false,
    name: 'Developer',
    permissions: [],
    priority: 10,
    slug: 'developer',
  }),
  getRoleServiceAccounts: vi.fn().mockResolvedValue([]),
  getRoleUsers: vi.fn().mockResolvedValue([]),
  grantPermission: vi.fn(),
  revokePermission: vi.fn(),
}))

describe('RoleDetail', () => {
  it('has no Groups tab, because teams do not grant roles', async () => {
    render(<RoleDetail onBack={vi.fn()} onEdit={vi.fn()} slug="developer" />)
    expect(await screen.findByText('Developer')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Users' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Groups' })).toBeNull()
  })
})

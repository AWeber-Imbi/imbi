import type { UseMutationResult } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'
import type { Role, ServiceAccount } from '@/types'

import { OrgMembershipsCard } from './OrgMembershipsCard'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ organizations: [] }),
}))

const mutation = {
  isPending: false,
  mutate: vi.fn(),
} as unknown as UseMutationResult<unknown, unknown, never>

describe('OrgMembershipsCard', () => {
  it('shows "No role" for a membership without a role', () => {
    const account = {
      organizations: [
        {
          organization_name: 'Acme',
          organization_slug: 'acme',
          role: null,
        },
      ],
      slug: 'bot',
    } as unknown as ServiceAccount
    render(
      <OrgMembershipsCard
        account={account}
        addOrgMutation={mutation}
        availableRoles={[{ name: 'Read Only', slug: 'readonly' } as Role]}
        onConfirmRemove={vi.fn()}
        removeOrgMutation={mutation}
        rolesError={false}
        rolesLoading={false}
        updateOrgRoleMutation={mutation}
      />,
    )
    expect(
      screen.getByRole('combobox', { name: 'Role for Acme' }),
    ).toHaveTextContent('No role')
  })
})

import type { UseMutationResult } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { listClientCredentials } from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { ServiceAccount } from '@/types'

import { ClientCredentialsSection } from '../ClientCredentialsSection'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  listClientCredentials: vi.fn(),
}))

const mutation = {
  isPending: false,
  mutate: vi.fn(),
} as unknown as UseMutationResult<never, unknown, never>

describe('ClientCredentialsSection', () => {
  it('suggests scopes that are permission names', async () => {
    vi.mocked(listClientCredentials).mockResolvedValue([])
    render(
      <ClientCredentialsSection
        account={{ slug: 'deploy-bot' } as ServiceAccount}
        createCredentialMutation={mutation}
        newlyCreatedCredential={null}
        onConfirmRevoke={vi.fn()}
        onConfirmRotate={vi.fn()}
        onNewlyCreatedCredentialChange={vi.fn()}
        revokeCredentialMutation={mutation}
        rotateCredentialMutation={mutation}
      />,
    )
    await userEvent.click(screen.getByText('Create Credential'))
    // The API answers 400 for a scope that is not a permission name.
    expect(screen.getByLabelText(/Scopes/)).toHaveAttribute(
      'placeholder',
      'e.g., project:read, project:write',
    )
  })
})

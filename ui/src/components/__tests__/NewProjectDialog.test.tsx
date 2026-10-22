import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { createProject } from '@/api/endpoints'
import { render } from '@/test/utils'

import { NewProjectDialog } from '../NewProjectDialog'

vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

vi.mock('@/hooks/useOrgResources', () => ({
  useEnvironments: () => ({
    data: [
      { name: 'Production', slug: 'production' },
      { name: 'Staging', slug: 'staging' },
    ],
    isLoading: false,
  }),
  useProjectTypes: () => ({
    data: [{ name: 'API', slug: 'api' }],
    isLoading: false,
  }),
  useTeams: () => ({
    data: [{ name: 'Platform', slug: 'platform' }],
    isLoading: false,
  }),
}))

// A native select stands in for the Combobox popover.
vi.mock('@/components/ui/combobox', () => ({
  Combobox: ({
    id,
    onChange,
    options,
    value,
  }: {
    id: string
    onChange: (v: string) => void
    options: { label: string; value: string }[]
    value: string
  }) => (
    <select id={id} onChange={(e) => onChange(e.target.value)} value={value}>
      <option value="" />
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  ),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    createProject: vi.fn().mockResolvedValue({ id: 'p1' }),
  }
})

describe('NewProjectDialog', () => {
  it('sends the selected environments as an environments map', async () => {
    const user = userEvent.setup()
    render(<NewProjectDialog isOpen onClose={() => {}} />)

    await user.selectOptions(screen.getByLabelText(/Team/), 'platform')
    await user.selectOptions(screen.getByLabelText(/Project Type/), 'api')
    await user.type(screen.getByLabelText(/Name/), 'My Service')
    await user.click(screen.getByRole('button', { name: 'Production' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(createProject).toHaveBeenCalled())
    const body = vi.mocked(createProject).mock.calls[0][1]
    expect(body.environments).toEqual({ production: {} })
    expect(body).not.toHaveProperty('environment_slugs')
  })
})

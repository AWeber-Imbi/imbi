import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { createProject, getNewProjectSchema } from '@/api/endpoints'
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
    getNewProjectSchema: vi.fn().mockResolvedValue({ sections: [] }),
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

  it('asks for required blueprint fields that have no default', async () => {
    vi.mocked(createProject).mockClear()
    vi.mocked(getNewProjectSchema).mockResolvedValue({
      sections: [
        {
          name: 'Service',
          properties: {
            owner: { default: 'ops', type: 'string' },
            tier: { title: 'Tier', type: 'string' },
          },
          required: ['tier', 'owner'],
          scope: 'project',
          slug: 'service',
        },
      ],
    })
    const user = userEvent.setup()
    render(<NewProjectDialog isOpen onClose={() => {}} />)

    await user.selectOptions(screen.getByLabelText(/Team/), 'platform')
    await user.selectOptions(screen.getByLabelText(/Project Type/), 'api')
    await user.type(screen.getByLabelText(/Name/), 'My Service')
    await user.click(screen.getByRole('button', { name: 'Production' }))

    await waitFor(() =>
      expect(getNewProjectSchema).toHaveBeenLastCalledWith(
        'acme',
        ['api'],
        ['production'],
        expect.anything(),
      ),
    )
    const tier = await screen.findByLabelText(/Tier/)
    expect(screen.queryByLabelText(/Owner/)).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(createProject).not.toHaveBeenCalled()

    await user.type(tier, 'gold')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(createProject).toHaveBeenCalled())
    const body = vi.mocked(createProject).mock.calls[0][1]
    expect(body.tier).toBe('gold')
    expect(body).not.toHaveProperty('owner')
  })

  it('keeps Save disabled until the blueprint schema loads', async () => {
    vi.mocked(getNewProjectSchema).mockReturnValue(new Promise(() => {}))
    const user = userEvent.setup()
    render(<NewProjectDialog isOpen onClose={() => {}} />)

    await user.selectOptions(screen.getByLabelText(/Team/), 'platform')
    await user.selectOptions(screen.getByLabelText(/Project Type/), 'api')
    await user.type(screen.getByLabelText(/Name/), 'My Service')

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('sends false for an unchecked required boolean', async () => {
    vi.mocked(createProject).mockClear()
    vi.mocked(getNewProjectSchema).mockResolvedValue({
      sections: [
        {
          name: 'Service',
          properties: { public: { title: 'Public', type: 'boolean' } },
          required: ['public'],
          scope: 'project',
          slug: 'service',
        },
      ],
    })
    const user = userEvent.setup()
    render(<NewProjectDialog isOpen onClose={() => {}} />)

    await user.selectOptions(screen.getByLabelText(/Team/), 'platform')
    await user.selectOptions(screen.getByLabelText(/Project Type/), 'api')
    await user.type(screen.getByLabelText(/Name/), 'My Service')
    await screen.findByLabelText(/Public/)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(createProject).toHaveBeenCalled())
    const body = vi.mocked(createProject).mock.calls[0][1]
    expect(body.public).toBe(false)
  })
})

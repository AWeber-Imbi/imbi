import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'
import type { ProjectType } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  deleteUpload: vi.fn(),
  getProjectTypeSchema: vi.fn(() => Promise.resolve(null)),
  getUploadThumbnailUrl: vi.fn(() => ''),
  uploadFile: vi.fn(),
}))

const selectedOrganization = { name: 'AWeber', slug: 'aweber' }

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({
    organizations: [selectedOrganization, { name: 'Other', slug: 'other' }],
    selectedOrganization,
  }),
}))

const { ProjectTypeForm } = await import('../ProjectTypeForm')

describe('ProjectTypeForm', () => {
  const onSave = vi.fn()

  beforeEach(() => {
    onSave.mockClear()
  })

  it('offers no organization picker', () => {
    render(
      <ProjectTypeForm onCancel={vi.fn()} onSave={onSave} projectType={null} />,
    )

    // The picker was a Select with this trigger id; nothing renders it now.
    expect(document.querySelector('#project-type-org')).toBeNull()
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.queryByText('Select organization...')).toBeNull()
  })

  it('saves against the organization selected in the top bar', () => {
    render(
      <ProjectTypeForm onCancel={vi.fn()} onSave={onSave} projectType={null} />,
    )

    fireEvent.change(screen.getByPlaceholderText('e.g., REST API'), {
      target: { value: 'Config Management' },
    })
    fireEvent.click(screen.getByRole('button', { name: /create project type/i }))

    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave.mock.calls[0][0]).toBe('aweber')
  })

  it('saves an existing project type against its own organization', () => {
    const projectType = {
      description: null,
      icon: null,
      name: 'Config Management',
      organization: { name: 'Other', slug: 'other' },
      slug: 'config-management',
    } as unknown as ProjectType

    render(
      <ProjectTypeForm
        onCancel={vi.fn()}
        onSave={onSave}
        projectType={projectType}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave.mock.calls[0][0]).toBe('other')
  })
})

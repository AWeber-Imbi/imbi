import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ProjectRepoProvider } from '@/contexts/ProjectRepoContext'
import { render } from '@/test/utils'

import { NewOpsLogDialog } from '../NewOpsLogDialog'

// vi.mock factories are hoisted above module-level constants.
const { PAGE_REPO, SELECTED_REPO } = vi.hoisted(() => ({
  PAGE_REPO: 'https://github.com/aweber-imbi/some-other-project',
  SELECTED_REPO: 'https://github.com/aweber-imbi/imbi',
}))

vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    getProject: vi.fn().mockResolvedValue({
      environments: [],
      id: 'p1',
      name: 'Imbi',
      services: [
        {
          dashboard_url: SELECTED_REPO,
          identifier: '1',
          integration_name: 'GitHub',
          integration_slug: 'github-com',
        },
      ],
      slug: 'imbi',
    }),
    getProjects: vi.fn().mockResolvedValue([{ id: 'p1', name: 'Imbi' }]),
    listIntegrations: vi
      .fn()
      .mockResolvedValue([{ plugin: 'github', slug: 'github-com' }]),
  }
})

describe('NewOpsLogDialog notes preview', () => {
  it("links #N against the selected project's repo, not the page's", async () => {
    const user = userEvent.setup()
    render(
      <ProjectRepoProvider repoUrl={PAGE_REPO}>
        <NewOpsLogDialog
          initialValues={{ notes: 'Rolled back #341', project_id: 'p1' }}
          isOpen
          onClose={() => {}}
        />
      </ProjectRepoProvider>,
    )

    await user.click(screen.getByRole('tab', { name: 'Preview' }))

    expect(await screen.findByRole('link', { name: '#341' })).toHaveAttribute(
      'href',
      `${SELECTED_REPO}/issues/341`,
    )
  })
})

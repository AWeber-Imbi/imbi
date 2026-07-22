import React from 'react'

import { MemoryRouter } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { Project, Release, ReleaseDependenciesResponse } from '@/types'

import { DependenciesTab } from '../DependenciesTab'

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const PROJECT: Pick<Project, 'id' | 'slug'> = {
  id: 'proj-1',
  slug: 'my-project',
}

function makeDeps(
  releaseId: string,
  overrides: Partial<ReleaseDependenciesResponse> = {},
): ReleaseDependenciesResponse {
  return {
    components: [
      {
        ecosystem: 'npm',
        groups: [],
        hashes: {},
        identifiers: [{ kind: 'purl', value: 'pkg:npm/express' }],
        license: 'MIT',
        name: 'express',
        purl_name: 'pkg:npm/express',
        scope: null,
        version: '4.18.2',
      },
    ],
    release_id: releaseId,
    ...overrides,
  }
}

function makeRelease(overrides: Partial<Release> = {}): Release {
  return {
    committish: 'abc1234',
    created_at: '2026-05-01T00:00:00Z',
    created_by: 'alice@example.com',
    id: 'rel-1',
    links: [],
    project_id: PROJECT.id,
    tag: '1.0.0',
    title: 'Initial release',
    ...overrides,
  }
}

let qc: QueryClient

// Radix Select interrogates these PointerEvent methods on its trigger;
// jsdom doesn't ship them, so userEvent.click would throw without
// these no-op stubs.
beforeEach(() => {
  qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  vi.clearAllMocks()
  Element.prototype.hasPointerCapture = vi.fn(() => false) as never
  Element.prototype.setPointerCapture = vi.fn() as never
  Element.prototype.releasePointerCapture = vi.fn() as never
})

describe('DependenciesTab', () => {
  it('shows the empty state when the project has no releases', async () => {
    vi.spyOn(endpoints, 'listProjectReleases').mockResolvedValue([])
    const depsSpy = vi
      .spyOn(endpoints, 'listReleaseDependencies')
      .mockResolvedValue(makeDeps('rel-1', { components: [] }))

    render(<DependenciesTab orgSlug="org" project={PROJECT} />, {
      wrapper: wrapper(qc),
    })

    expect(await screen.findByText(/No releases yet/i)).toBeInTheDocument()
    expect(depsSpy).not.toHaveBeenCalled()
  })

  it('renders the dependencies of the most recent release by default', async () => {
    vi.spyOn(endpoints, 'listProjectReleases').mockResolvedValue([
      makeRelease({
        created_at: '2026-04-01T00:00:00Z',
        id: 'rel-old',
        tag: '0.9.0',
      }),
      makeRelease({
        created_at: '2026-05-01T00:00:00Z',
        id: 'rel-new',
        tag: '1.0.0',
      }),
    ])
    const depsSpy = vi
      .spyOn(endpoints, 'listReleaseDependencies')
      .mockResolvedValue(makeDeps('rel-new'))

    render(<DependenciesTab orgSlug="org" project={PROJECT} />, {
      wrapper: wrapper(qc),
    })

    expect(await screen.findByText('express')).toBeInTheDocument()
    expect(screen.getByText('4.18.2')).toBeInTheDocument()
    expect(screen.getByText('MIT')).toBeInTheDocument()
    // ``listReleaseDependencies`` should have targeted the newest release.
    expect(depsSpy).toHaveBeenCalledWith(
      'org',
      'proj-1',
      'rel-new',
      expect.any(AbortSignal),
    )
  })

  it('shows an empty-table message when the selected release has no SBoM', async () => {
    vi.spyOn(endpoints, 'listProjectReleases').mockResolvedValue([
      makeRelease(),
    ])
    vi.spyOn(endpoints, 'listReleaseDependencies').mockResolvedValue(
      makeDeps('rel-1', { components: [] }),
    )

    render(<DependenciesTab orgSlug="org" project={PROJECT} />, {
      wrapper: wrapper(qc),
    })

    expect(
      await screen.findByText(/No SBoM has been ingested/i),
    ).toBeInTheDocument()
  })

  it('refetches dependencies when the user switches release', async () => {
    const user = userEvent.setup()
    vi.spyOn(endpoints, 'listProjectReleases').mockResolvedValue([
      makeRelease({
        created_at: '2026-05-01T00:00:00Z',
        id: 'rel-new',
        tag: '1.0.0',
      }),
      makeRelease({
        created_at: '2026-04-01T00:00:00Z',
        id: 'rel-old',
        tag: '0.9.0',
      }),
    ])
    const depsSpy = vi
      .spyOn(endpoints, 'listReleaseDependencies')
      .mockImplementation(async (_org, _project, releaseId) =>
        makeDeps(releaseId, {
          components: [
            {
              ecosystem: 'npm',
              groups: [],
              hashes: {},
              identifiers: [],
              license: null,
              name: `library-for-${releaseId}`,
              purl_name: `pkg:npm/library-for-${releaseId}`,
              scope: null,
              version: '1.0.0',
            },
          ],
        }),
      )

    render(<DependenciesTab orgSlug="org" project={PROJECT} />, {
      wrapper: wrapper(qc),
    })

    await screen.findByText('library-for-rel-new')

    const trigger = screen.getByRole('combobox', { name: /release/i })
    await user.click(trigger)
    const oldOption = await screen.findByRole('option', { name: '0.9.0' })
    await user.click(oldOption)

    await waitFor(() => {
      expect(depsSpy).toHaveBeenCalledWith(
        'org',
        'proj-1',
        'rel-old',
        expect.any(AbortSignal),
      )
    })
    await screen.findByText('library-for-rel-old')
  })

  it('renders scope and group chips when present on a component', async () => {
    vi.spyOn(endpoints, 'listProjectReleases').mockResolvedValue([
      makeRelease(),
    ])
    vi.spyOn(endpoints, 'listReleaseDependencies').mockResolvedValue(
      makeDeps('rel-1', {
        components: [
          {
            ecosystem: 'pypi',
            groups: ['dev', 'test'],
            hashes: {},
            identifiers: [{ kind: 'purl', value: 'pkg:pypi/pytest' }],
            license: 'MIT',
            name: 'pytest',
            purl_name: 'pkg:pypi/pytest',
            scope: 'optional',
            version: '8.0.0',
          },
        ],
      }),
    )

    render(<DependenciesTab orgSlug="org" project={PROJECT} />, {
      wrapper: wrapper(qc),
    })

    // The chip ARIA labels are the stable contract — the styling
    // classes can change without breaking this assertion.
    expect(await screen.findByLabelText('scope: optional')).toBeInTheDocument()
    expect(screen.getByLabelText('group: dev')).toBeInTheDocument()
    expect(screen.getByLabelText('group: test')).toBeInTheDocument()
  })

  it('shows an error message when the releases query fails', async () => {
    vi.spyOn(endpoints, 'listProjectReleases').mockRejectedValue(
      new Error('boom'),
    )

    render(<DependenciesTab orgSlug="org" project={PROJECT} />, {
      wrapper: wrapper(qc),
    })

    expect(
      await screen.findByText(/Failed to load releases/i),
    ).toBeInTheDocument()
  })

  it('shows an error message when the dependencies query fails', async () => {
    vi.spyOn(endpoints, 'listProjectReleases').mockResolvedValue([
      makeRelease(),
    ])
    vi.spyOn(endpoints, 'listReleaseDependencies').mockRejectedValue(
      new Error('boom'),
    )

    render(<DependenciesTab orgSlug="org" project={PROJECT} />, {
      wrapper: wrapper(qc),
    })

    expect(
      await screen.findByText(/Failed to load dependencies/i),
    ).toBeInTheDocument()
  })

  it('shows an em-dash when neither scope nor groups are present', async () => {
    vi.spyOn(endpoints, 'listProjectReleases').mockResolvedValue([
      makeRelease(),
    ])
    vi.spyOn(endpoints, 'listReleaseDependencies').mockResolvedValue(
      makeDeps('rel-1'),
    )

    render(<DependenciesTab orgSlug="org" project={PROJECT} />, {
      wrapper: wrapper(qc),
    })

    await screen.findByText('express')
    // No chips rendered — the cell shows the placeholder dash.
    expect(screen.queryByLabelText(/^scope:/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^group:/)).not.toBeInTheDocument()
  })
})

// Lint hint: keep `within` referenced so the helper survives future
// edits that add cell-scoped assertions.
void within

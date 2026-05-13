import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { ActivityFeedEntry, OperationsLogEntry } from '@/types'

import { RecentActivity } from '../RecentActivity'

function makeOps(
  overrides: Partial<OperationsLogEntry> = {},
): OperationsLogEntry {
  return {
    change_type: 'Deployed',
    description: '',
    display_name: 'Alex S',
    email_address: 'alexs@aweber.com',
    environment: 'production',
    id: 1,
    occurred_at: '2026-05-12T02:24:59.841Z',
    performed_by: 'alexs',
    project_id: 1,
    project_name: 'ai-content',
    recorded_at: '2026-05-12T02:24:59.841Z',
    recorded_by: 'alexs',
    type: 'OperationsLogEntry',
    version: 'v1.2.3',
    ...overrides,
  }
}

function projectFeed(
  overrides: Partial<
    Extract<ActivityFeedEntry, { type: 'ProjectFeedEntry' }>
  > = {},
): Extract<ActivityFeedEntry, { type: 'ProjectFeedEntry' }> {
  return {
    display_name: 'Alex S',
    email_address: 'alexs@aweber.com',
    project_id: 1,
    project_name: 'ai-content',
    project_slug: 'ai-content',
    type: 'ProjectFeedEntry',
    what: 'created',
    when: '2026-05-12T02:24:59.841Z',
    who: 'alexs',
    ...overrides,
  } as Extract<ActivityFeedEntry, { type: 'ProjectFeedEntry' }>
}

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

let qc: QueryClient

beforeEach(() => {
  qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  vi.clearAllMocks()
  // Default: no plugin templates available -- exercises fallback rendering.
  vi.spyOn(endpoints, 'listPluginOpsLogTemplates').mockResolvedValue([])
})

describe('RecentActivity', () => {
  it('renders the loading state', () => {
    render(<RecentActivity activities={[]} isLoading />, {
      wrapper: wrapper(qc),
    })
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('renders the empty state', () => {
    render(<RecentActivity activities={[]} />, { wrapper: wrapper(qc) })
    expect(screen.getByText('No recent activity')).toBeInTheDocument()
  })

  it('renders the heading by default and hides it on hideHeading', () => {
    const { rerender } = render(<RecentActivity activities={[]} />, {
      wrapper: wrapper(qc),
    })
    expect(screen.getByText('Recent Activity')).toBeInTheDocument()
    rerender(<RecentActivity activities={[]} hideHeading />)
    expect(screen.queryByText('Recent Activity')).not.toBeInTheDocument()
  })

  it('renders an ops-log fallback sentence for Deployed entries', () => {
    render(<RecentActivity activities={[makeOps()]} />, {
      wrapper: wrapper(qc),
    })
    expect(screen.getByText(/to the/)).toBeInTheDocument()
    expect(screen.getByText(/production environment\./)).toBeInTheDocument()
    expect(screen.getByText(/\(v1\.2\.3\)/)).toBeInTheDocument()
  })

  it('renders the configured/in-the variant for non-deploy ops-log entries', () => {
    render(
      <RecentActivity
        activities={[makeOps({ change_type: 'Configured', version: null })]}
      />,
      { wrapper: wrapper(qc) },
    )
    expect(screen.getByText(/in the/)).toBeInTheDocument()
    // No version chip when version is null.
    expect(screen.queryByText(/\(v\d/)).not.toBeInTheDocument()
  })

  it('renders project-feed entries with the "updated facts" phrasing', () => {
    render(
      <RecentActivity activities={[projectFeed({ what: 'updated facts' })]} />,
      { wrapper: wrapper(qc) },
    )
    expect(screen.getByText(/updated facts for the/)).toBeInTheDocument()
  })

  it('renders project-feed entries with the generic "what" phrasing', () => {
    const { container } = render(
      <RecentActivity activities={[projectFeed({ what: 'created' })]} />,
      { wrapper: wrapper(qc) },
    )
    // The literal "what" value appears verbatim and the "updated facts"
    // rewrite is not used.
    expect(container.textContent).toMatch(/created/)
    expect(container.textContent).not.toMatch(/updated facts for the/)
  })

  it('fires onUserSelect when the display name is clicked', async () => {
    const onUserSelect = vi.fn()
    render(
      <RecentActivity
        activities={[makeOps({ display_name: 'Alex S' })]}
        onUserSelect={onUserSelect}
      />,
      { wrapper: wrapper(qc) },
    )
    await userEvent.click(screen.getByText('Alex S'))
    expect(onUserSelect).toHaveBeenCalledWith('Alex S')
  })

  it('fires onProjectSelect when the project name is clicked', async () => {
    const onProjectSelect = vi.fn()
    render(
      <RecentActivity
        activities={[makeOps({ project_name: 'ai-content' })]}
        onProjectSelect={onProjectSelect}
      />,
      { wrapper: wrapper(qc) },
    )
    await userEvent.click(screen.getByText('ai-content'))
    expect(onProjectSelect).toHaveBeenCalledWith('ai-content')
  })

  it('shows a Load more button and fires onLoadMore when clicked', async () => {
    const onLoadMore = vi.fn()
    render(
      <RecentActivity activities={[makeOps()]} onLoadMore={onLoadMore} />,
      { wrapper: wrapper(qc) },
    )
    const button = screen.getByText('Load more activity')
    await userEvent.click(button)
    expect(onLoadMore).toHaveBeenCalled()
  })

  it('disables the load more button while loading more', () => {
    render(
      <RecentActivity
        activities={[makeOps()]}
        isLoadingMore
        onLoadMore={() => {}}
      />,
      { wrapper: wrapper(qc) },
    )
    expect(screen.getByText('Loading more...')).toBeInTheDocument()
  })
})

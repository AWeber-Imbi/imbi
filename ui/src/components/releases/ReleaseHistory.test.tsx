import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as releases from '@/api/releases'
import { render } from '@/test/utils'
import type { ReleaseHistoryEntry } from '@/types'

import { deriveArtifact } from './artifact'
import { ReleaseHistory } from './ReleaseHistory'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/releases', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/releases')>('@/api/releases')
  return { ...actual, blockRelease: vi.fn(), unblockRelease: vi.fn() }
})

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

const blockRelease = vi.mocked(releases.blockRelease)
const unblockRelease = vi.mocked(releases.unblockRelease)

const RELEASES: ReleaseHistoryEntry[] = [
  {
    author: 'Gavin',
    ci_status: 'pass',
    notes_markdown: '## Added\n- A thing',
    published_at: '2026-01-02T00:00:00Z',
    release_url: 'https://gh/releases/v1.1.0',
    sha: 'aaa1111bbb',
    short_sha: 'aaa1111',
    tag: 'v1.1.0',
  },
  {
    author: 'Kevin',
    ci_status: 'warn',
    notes_markdown: null,
    published_at: '2026-01-01T00:00:00Z',
    release_url: null,
    sha: 'ccc2222ddd',
    short_sha: 'ccc2222',
    tag: 'v1.0.0',
  },
]

const ARTIFACT = deriveArtifact({ links: {}, name: 'lib' })

const renderHistory = (
  releases: ReleaseHistoryEntry[],
  currentTag: null | string = 'v1.1.0',
) =>
  render(
    <ReleaseHistory
      artifact={ARTIFACT}
      currentTag={currentTag}
      orgSlug="acme"
      projectId="p1"
      releases={releases}
    />,
  )

describe('ReleaseHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    blockRelease.mockResolvedValue({ blocked: true, tag: 'v1.1.0' })
    unblockRelease.mockResolvedValue({ blocked: false, tag: 'v1.0.0' })
  })

  it('renders each release with a Latest badge on the current tag', () => {
    renderHistory(RELEASES)
    expect(screen.getByText('v1.1.0')).toBeInTheDocument()
    expect(screen.getByText('v1.0.0')).toBeInTheDocument()
    expect(screen.getByText('Latest')).toBeInTheDocument()
  })

  it('expands a row to render its markdown notes', async () => {
    const user = userEvent.setup()
    renderHistory(RELEASES)
    await user.click(screen.getByRole('button', { name: /v1\.1\.0/ }))
    expect(screen.getByText('A thing')).toBeInTheDocument()
  })

  it('renders nothing when there are no releases', () => {
    const { container } = renderHistory([], null)
    expect(container).toBeEmptyDOMElement()
  })

  it('marks a blocked release and shows why, who, and an unblock action', async () => {
    const user = userEvent.setup()
    renderHistory([
      {
        ...RELEASES[1],
        blocked: true,
        blocked_at: '2026-01-03T00:00:00Z',
        blocked_by: 'gavinr@aweber.com',
        blocked_reason: 'Regression in the checkout flow',
      },
    ])
    expect(screen.getByText('Blocked')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /v1\.0\.0/ }))
    expect(
      screen.getByText(/Regression in the checkout flow/),
    ).toBeInTheDocument()
    expect(screen.getByText(/gavinr@aweber\.com/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Unblock' }))
    expect(unblockRelease).toHaveBeenCalledWith('acme', 'p1', 'v1.0.0')
  })

  it('blocks a release with the reason from the dialog', async () => {
    const user = userEvent.setup()
    renderHistory(RELEASES)
    await user.click(screen.getByRole('button', { name: /v1\.1\.0/ }))
    await user.click(screen.getByRole('button', { name: /Block release/ }))

    const submit = screen.getByRole('button', { name: 'Block v1.1.0' })
    // The reason is required — no reason, no block.
    expect(submit).toBeDisabled()

    await user.type(screen.getByRole('textbox'), 'Rolled back — regression')
    await user.click(submit)
    await waitFor(() =>
      expect(blockRelease).toHaveBeenCalledWith('acme', 'p1', 'v1.1.0', {
        reason: 'Rolled back — regression',
      }),
    )
  })
})

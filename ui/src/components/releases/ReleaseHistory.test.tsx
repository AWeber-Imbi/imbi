import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { render } from '@/test/utils'
import type { ReleaseHistoryEntry } from '@/types'

import { deriveArtifact } from './artifact'
import { ReleaseHistory } from './ReleaseHistory'

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

describe('ReleaseHistory', () => {
  it('renders each release with a Latest badge on the current tag', () => {
    render(
      <ReleaseHistory
        artifact={ARTIFACT}
        currentTag="v1.1.0"
        releases={RELEASES}
      />,
    )
    expect(screen.getByText('v1.1.0')).toBeInTheDocument()
    expect(screen.getByText('v1.0.0')).toBeInTheDocument()
    expect(screen.getByText('Latest')).toBeInTheDocument()
  })

  it('expands a row to render its markdown notes', async () => {
    const user = userEvent.setup()
    render(
      <ReleaseHistory
        artifact={ARTIFACT}
        currentTag="v1.1.0"
        releases={RELEASES}
      />,
    )
    await user.click(screen.getByRole('button', { name: /v1\.1\.0/ }))
    expect(screen.getByText('A thing')).toBeInTheDocument()
  })

  it('renders nothing when there are no releases', () => {
    const { container } = render(
      <ReleaseHistory artifact={ARTIFACT} currentTag={null} releases={[]} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

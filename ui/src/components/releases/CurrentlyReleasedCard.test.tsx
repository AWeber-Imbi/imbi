import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { render } from '@/test/utils'
import type { ReleaseHistoryEntry } from '@/types'

import { deriveArtifact } from './artifact'
import { CurrentlyReleasedCard } from './CurrentlyReleasedCard'

const RELEASE: ReleaseHistoryEntry = {
  author: 'Gavin',
  ci_status: 'pass',
  notes_markdown: '## Notes',
  published_at: '2026-01-01T00:00:00Z',
  release_url: 'https://gh/releases/v1.0.0',
  sha: 'abc1234def',
  short_sha: 'abc1234',
  tag: 'v1.0.0',
}

describe('CurrentlyReleasedCard', () => {
  it('renders the tag, sha and author', () => {
    render(
      <CurrentlyReleasedCard
        artifact={deriveArtifact({ links: {}, name: 'lib' })}
        released={RELEASE}
      />,
    )
    expect(screen.getByText('v1.0.0')).toBeInTheDocument()
    expect(screen.getByText('abc1234')).toBeInTheDocument()
    expect(screen.getByText('Gavin')).toBeInTheDocument()
  })

  it('hides the pull command and index link for an unknown artifact', () => {
    render(
      <CurrentlyReleasedCard
        artifact={deriveArtifact({ links: {}, name: 'lib' })}
        released={RELEASE}
      />,
    )
    expect(screen.queryByText(/pip install|docker pull/)).toBeNull()
    expect(screen.queryByText('Package index')).toBeNull()
  })

  it('shows a pull command for a pypi-linked project', () => {
    render(
      <CurrentlyReleasedCard
        artifact={deriveArtifact({
          links: { pypi: 'https://pypi.org/project/address-verification' },
          name: 'address-verification',
        })}
        released={RELEASE}
      />,
    )
    expect(
      screen.getByText('pip install address-verification'),
    ).toBeInTheDocument()
  })

  it('renders an empty state when nothing is released', () => {
    render(
      <CurrentlyReleasedCard
        artifact={deriveArtifact({ links: {}, name: 'lib' })}
        released={null}
      />,
    )
    expect(screen.getByText('No releases published yet.')).toBeInTheDocument()
  })
})

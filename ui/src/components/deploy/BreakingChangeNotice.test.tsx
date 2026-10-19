import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render } from '@/test/utils'
import type { BreakingChange } from '@/types'

import {
  BreakingChangeNotice,
  breakingNeedsAcknowledgement,
  skipsBreakingBump,
} from './BreakingChangeNotice'

const CHANGES: BreakingChange[] = [
  {
    commit: 'b7e1d2c',
    declared: true,
    description: 'Drop the v1 routes',
    url: 'https://gh/commit/b7e1d2c',
  },
  { commit: 'c0ffee1', description: 'Rename the export field' },
]

function renderNotice(
  overrides: Partial<{
    acknowledged: boolean
    breakingChanges: BreakingChange[] | undefined
    lastTag: null | string
    onAcknowledgedChange: (next: boolean) => void
    tag: string
  }> = {},
) {
  return render(
    <BreakingChangeNotice
      acknowledged={overrides.acknowledged ?? false}
      action="promote"
      breakingChanges={
        'breakingChanges' in overrides ? overrides.breakingChanges : CHANGES
      }
      lastTag={'lastTag' in overrides ? (overrides.lastTag ?? null) : 'v6.3.0'}
      onAcknowledgedChange={overrides.onAcknowledgedChange ?? vi.fn()}
      tag={overrides.tag ?? 'v6.4.0'}
    />,
  )
}

describe('skipsBreakingBump', () => {
  it('matches the API gate', () => {
    const cases: [string, string, boolean][] = [
      ['v6.3.0', 'v6.4.0', true],
      ['v6.3.0', 'v6.3.1', true],
      ['6.3.0', '7.0.0', false],
      // Not newer: re-promoting a tag, or a backport.
      ['v6.3.0', 'v6.3.0', false],
      ['v6.3.0', 'v5.9.9', false],
      // Below 1.0.0 the minor carries the break.
      ['0.3.0', '0.3.1', true],
      ['0.3.0', '0.4.0', false],
      ['0.3.0', '1.0.0', false],
      // Nothing to judge without two semver tags.
      ['2026.09.17', '2026.09.18', false],
      ['v6.3.0', 'vX.Y.Z', false],
    ]
    for (const [lastTag, tag, expected] of cases) {
      expect(skipsBreakingBump(lastTag, tag), `${lastTag} → ${tag}`).toBe(
        expected,
      )
    }
  })
})

describe('breakingNeedsAcknowledgement', () => {
  it('needs breaking changes, a prior release and a non-breaking bump', () => {
    expect(breakingNeedsAcknowledgement(CHANGES, 'v6.3.0', 'v6.4.0')).toBe(true)
    expect(breakingNeedsAcknowledgement(CHANGES, 'v6.3.0', 'v7.0.0')).toBe(
      false,
    )
    expect(breakingNeedsAcknowledgement([], 'v6.3.0', 'v6.4.0')).toBe(false)
    // The draft has not run yet.
    expect(breakingNeedsAcknowledgement(undefined, 'v6.3.0', 'v6.4.0')).toBe(
      false,
    )
    // First release: nothing to break.
    expect(breakingNeedsAcknowledgement(CHANGES, null, 'v0.1.0')).toBe(false)
  })
})

describe('BreakingChangeNotice', () => {
  it('renders nothing without breaking changes', () => {
    renderNotice({ breakingChanges: [] })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('lists the evidence as a warning for a breaking-change bump', () => {
    renderNotice({ tag: 'v7.0.0' })
    expect(
      screen.getByText('2 breaking changes in this release'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'b7e1d2c' })).toHaveAttribute(
      'href',
      'https://gh/commit/b7e1d2c',
    )
    expect(screen.getByText('Rename the export field')).toBeInTheDocument()
    expect(
      screen.getByText(/marked breaking by its author/),
    ).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('asks for an acknowledgement when the tag hides them', async () => {
    const onAcknowledgedChange = vi.fn()
    renderNotice({ onAcknowledgedChange })
    expect(
      screen.getByText('v6.4.0 is not a breaking-change release'),
    ).toBeInTheDocument()
    expect(screen.getByText(/Release a major version instead/)).toBeVisible()
    await userEvent.click(
      screen.getByRole('checkbox', {
        name: 'Promote v6.4.0 anyway despite the breaking changes',
      }),
    )
    expect(onAcknowledgedChange).toHaveBeenCalledWith(true)
  })

  it('asks for a minor below 1.0.0', () => {
    renderNotice({ lastTag: '0.3.0', tag: '0.3.1' })
    expect(screen.getByText(/Release a minor version instead/)).toBeVisible()
  })
})

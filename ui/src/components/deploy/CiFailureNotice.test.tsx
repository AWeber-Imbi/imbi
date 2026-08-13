import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render } from '@/test/utils'
import type { DeploymentCommitCiStatus } from '@/types'

import { CiFailureNotice, ciNeedsAcknowledgement } from './CiFailureNotice'

function renderNotice(
  ciStatus: DeploymentCommitCiStatus | undefined,
  overrides: Partial<{
    acknowledged: boolean
    action: 'promote' | 'release'
    onAcknowledgedChange: (next: boolean) => void
  }> = {},
) {
  return render(
    <CiFailureNotice
      acknowledged={overrides.acknowledged ?? false}
      action={overrides.action ?? 'promote'}
      ciStatus={ciStatus}
      onAcknowledgedChange={overrides.onAcknowledgedChange ?? vi.fn()}
      sha="aaa1111bbbb2222"
    />,
  )
}

describe('ciNeedsAcknowledgement', () => {
  it('gates on a failure and nothing else', () => {
    expect(ciNeedsAcknowledgement('fail')).toBe(true)
    // `warn` is a cancelled or stale run, not a failing one; `unknown`
    // means CI never ran or the token cannot read check-runs. Gating on
    // either would put a confirmation in front of most promotes.
    expect(ciNeedsAcknowledgement('warn')).toBe(false)
    expect(ciNeedsAcknowledgement('pass')).toBe(false)
    expect(ciNeedsAcknowledgement('unknown')).toBe(false)
    // Still loading.
    expect(ciNeedsAcknowledgement(undefined)).toBe(false)
  })
})

describe('CiFailureNotice', () => {
  it('renders nothing for a status that does not gate', () => {
    for (const status of ['pass', 'warn', 'unknown', undefined] as const) {
      const { unmount } = renderNotice(status)
      expect(screen.queryByText(/CI failed/)).not.toBeInTheDocument()
      unmount()
    }
  })

  it('names the short sha so the warning is about a specific commit', () => {
    renderNotice('fail')
    expect(screen.getByText('CI failed for aaa1111')).toBeInTheDocument()
  })

  it('reports the acknowledgement upward rather than owning it', async () => {
    // The submit button lives in the parent form, so the parent has to own
    // the flag — this component only reports the toggle.
    const onAcknowledgedChange = vi.fn()
    renderNotice('fail', { onAcknowledgedChange })
    const box = screen.getByRole('checkbox', { name: /Promote anyway/i })
    expect(box).not.toBeChecked()
    await userEvent.setup().click(box)
    expect(onAcknowledgedChange).toHaveBeenCalledWith(true)
  })

  it('reflects the acknowledgement the parent holds', () => {
    renderNotice('fail', { acknowledged: true })
    expect(
      screen.getByRole('checkbox', { name: /Promote anyway/i }),
    ).toBeChecked()
  })

  it("uses the caller's verb", () => {
    renderNotice('fail', { action: 'release' })
    expect(
      screen.getByRole('checkbox', { name: /Release anyway/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Releasing anyway is still your call/),
    ).toBeInTheDocument()
  })
})

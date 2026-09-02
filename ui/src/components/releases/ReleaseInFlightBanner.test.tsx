import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render } from '@/test/utils'

import type { ReleaseInFlightState } from './releaseInFlight'
import {
  type InFlightKind,
  ReleaseInFlightBanner,
} from './ReleaseInFlightBanner'

const state = (
  over: Partial<ReleaseInFlightState> = {},
): ReleaseInFlightState => ({
  blocked: true,
  cutBlocked: true,
  dismiss: vi.fn(),
  endedAt: null,
  envName: 'Staging',
  error: null,
  phase: 'building',
  runUrl: 'https://github.com/acme/demo/actions/runs/1',
  startedAt: new Date(Date.now() - 90_000).toISOString(),
  tag: 'v6.5.0',
  ...over,
})

function renderBanner(
  over: Partial<ReleaseInFlightState> = {},
  kind: InFlightKind = 'promote',
) {
  const onRedeploy = vi.fn()
  const onUnblock = vi.fn()
  const value = state(over)
  render(
    <ReleaseInFlightBanner
      kind={kind}
      onRedeploy={onRedeploy}
      onUnblock={onUnblock}
      state={value}
      unblockPending={false}
    />,
  )
  return { onRedeploy, onUnblock, value }
}

describe('ReleaseInFlightBanner', () => {
  it('renders nothing when no release is running', () => {
    const { container } = render(
      <ReleaseInFlightBanner
        kind="promote"
        onRedeploy={vi.fn()}
        onUnblock={vi.fn()}
        state={state({ blocked: false, phase: 'idle' })}
        unblockPending={false}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('says it is still asking before the first poll answers', () => {
    renderBanner({ phase: 'adopting' })
    expect(
      screen.getByText('Checking for a release in flight…'),
    ).toBeInTheDocument()
  })

  it('walks the phase train and counts elapsed time while building', () => {
    renderBanner({ phase: 'building' })
    expect(screen.getByText('Building release v6.5.0…')).toBeInTheDocument()
    expect(screen.getByText('Building')).toBeInTheDocument()
    expect(screen.getByText('Deploying')).toBeInTheDocument()
    expect(screen.getByText('Released')).toBeInTheDocument()
    expect(screen.getByText('1m 30s')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View build' })).toHaveAttribute(
      'href',
      'https://github.com/acme/demo/actions/runs/1',
    )
  })

  it('has no deploying step for a release-only cut', () => {
    renderBanner({ envName: null, phase: 'building' }, 'release')
    expect(screen.getByText('Building')).toBeInTheDocument()
    expect(screen.queryByText('Deploying')).not.toBeInTheDocument()
    expect(screen.getByText('Released')).toBeInTheDocument()
  })

  it('names the target environment while deploying', () => {
    renderBanner({ phase: 'deploying' })
    expect(screen.getByText('Deploying v6.5.0 to Staging…')).toBeInTheDocument()
  })

  it('offers an unblock on a failed build, because the tag is blocked', async () => {
    const user = userEvent.setup()
    const { onUnblock } = renderBanner({ phase: 'build_failed' })
    expect(screen.getByText(/The tag is blocked/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Unblock v6.5.0' }))
    expect(onUnblock).toHaveBeenCalledWith('v6.5.0')
  })

  it('offers a redeploy on a failed deploy, because the tag is not blocked', async () => {
    const user = userEvent.setup()
    const { onRedeploy } = renderBanner({
      blocked: false,
      phase: 'deploy_failed',
    })
    expect(screen.getByText(/the release is not blocked/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Redeploy v6\.5\.0/ }))
    expect(onRedeploy).toHaveBeenCalled()
  })

  it('caveats an outcome Imbi lost track of', () => {
    renderBanner({ blocked: false, phase: 'failed' })
    expect(screen.getByText(/Last promote outcome unknown/)).toBeInTheDocument()
  })

  it('prefers the plugin-reported error over the generic copy', () => {
    renderBanner({ error: 'workflow release.yml not found', phase: 'failed' })
    expect(
      screen.getByText('workflow release.yml not found'),
    ).toBeInTheDocument()
  })

  it('persists a success until it is dismissed', async () => {
    const user = userEvent.setup()
    const { value } = renderBanner({ blocked: false, phase: 'success' })
    expect(screen.getByText('Released v6.5.0 to Staging')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(value.dismiss).toHaveBeenCalled()
  })

  it('freezes the clock at how long a finished release took', () => {
    // Both stamps off one reading: two `Date.now()` calls can straddle a
    // millisecond and turn the expected 60s into 59.
    const base = Date.now()
    renderBanner({
      blocked: false,
      endedAt: new Date(base - 30_000).toISOString(),
      phase: 'success',
      startedAt: new Date(base - 90_000).toISOString(),
    })
    expect(screen.getByText('1m 0s')).toBeInTheDocument()
  })

  it('offers no dismiss while a release is still running', () => {
    renderBanner({ phase: 'building' })
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull()
  })

  it('omits the build link when the plugin reported no run URL', () => {
    renderBanner({ runUrl: null })
    expect(screen.queryByRole('link', { name: 'View build' })).toBeNull()
  })
})

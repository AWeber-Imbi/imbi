import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listSecretBindings, listSecretProviders } from '@/api/endpoints'
import { render, screen } from '@/test/utils'

import { GitHubAppBindingSelect } from '../GitHubAppBindingSelect'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  listSecretBindings: vi.fn(),
  listSecretProviders: vi.fn(),
}))

describe('GitHubAppBindingSelect', () => {
  beforeEach(() => {
    // jsdom has no pointer capture or scrollIntoView; Radix Select needs them.
    Element.prototype.hasPointerCapture = vi.fn(() => false) as never
    Element.prototype.setPointerCapture = vi.fn() as never
    Element.prototype.releasePointerCapture = vi.fn() as never
    Element.prototype.scrollIntoView = vi.fn() as never
    vi.mocked(listSecretProviders).mockResolvedValue([
      { enabled: true, id: 'p-app', type: 'github_app' },
      { enabled: false, id: 'p-off', type: 'github_app' },
      { enabled: true, id: 'p-aws', type: 'aws_secrets_manager' },
    ] as never)
    vi.mocked(listSecretBindings).mockResolvedValue([
      {
        enabled: true,
        provider_id: 'p-app',
        reference: 'secret://production/github/app',
      },
      {
        enabled: false,
        provider_id: 'p-app',
        reference: 'secret://production/github/disabled',
      },
      {
        enabled: true,
        provider_id: 'p-off',
        reference: 'secret://production/github/off',
      },
      {
        enabled: true,
        provider_id: 'p-aws',
        reference: 'secret://production/github/key',
      },
    ] as never)
  })

  it('lists only github_app bindings and returns the reference', async () => {
    const onChange = vi.fn()
    render(
      <GitHubAppBindingSelect
        onChange={onChange}
        orgSlug="acme"
        value={null}
      />,
    )
    await userEvent.click(screen.getByLabelText('GitHub App binding'))
    const option = await screen.findByRole('option', {
      name: 'secret://production/github/app',
    })
    for (const name of [
      'secret://production/github/key',
      'secret://production/github/disabled',
      'secret://production/github/off',
    ]) {
      expect(screen.queryByRole('option', { name })).toBeNull()
    }
    await userEvent.click(option)
    expect(onChange).toHaveBeenCalledWith('secret://production/github/app')
  })

  it('clears the value with the none option', async () => {
    const onChange = vi.fn()
    render(
      <GitHubAppBindingSelect
        onChange={onChange}
        orgSlug="acme"
        value="secret://production/github/app"
      />,
    )
    await userEvent.click(screen.getByLabelText('GitHub App binding'))
    await userEvent.click(
      await screen.findByRole('option', { name: 'No GitHub App' }),
    )
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('keeps a saved disabled binding visible', async () => {
    render(
      <GitHubAppBindingSelect
        onChange={vi.fn()}
        orgSlug="acme"
        value="secret://production/github/disabled"
      />,
    )
    await userEvent.click(screen.getByLabelText('GitHub App binding'))
    expect(
      await screen.findByRole('option', {
        name: 'secret://production/github/disabled',
      }),
    ).toBeInTheDocument()
  })
})

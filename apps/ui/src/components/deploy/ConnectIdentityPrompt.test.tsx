import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ConnectIdentityPrompt } from './ConnectIdentityPrompt'

describe('ConnectIdentityPrompt', () => {
  it('names the provider and wires the connect/manage actions', () => {
    const onConnect = vi.fn()
    const onManage = vi.fn()
    render(
      <ConnectIdentityPrompt
        action="deploy"
        label="GitHub Enterprise Cloud"
        onConnect={onConnect}
        onManage={onManage}
        serviceIcon={null}
      />,
    )

    expect(
      screen.getByText('Not connected to GitHub Enterprise Cloud'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Connect your account to deploy this project.'),
    ).toBeInTheDocument()

    fireEvent.click(
      screen.getByRole('button', { name: 'Connect GitHub Enterprise Cloud' }),
    )
    expect(onConnect).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Manage' }))
    expect(onManage).toHaveBeenCalledTimes(1)
  })

  it('uses release wording for the release action', () => {
    render(
      <ConnectIdentityPrompt
        action="release"
        label="GitHub"
        onConnect={vi.fn()}
        onManage={vi.fn()}
        serviceIcon={null}
      />,
    )

    expect(
      screen.getByText(
        'Connect your account to cut releases for this project.',
      ),
    ).toBeInTheDocument()
  })
})

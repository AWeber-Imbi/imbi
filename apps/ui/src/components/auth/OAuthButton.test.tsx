import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'

import { OAuthButton } from './OAuthButton'

describe('OAuthButton', () => {
  const mockOnClick = vi.fn()

  const defaultProvider = {
    icon: 'google',
    id: 'google',
    name: 'Google',
  }

  beforeEach(() => {
    mockOnClick.mockClear()
  })

  it('should render button with provider name', () => {
    render(<OAuthButton onClick={mockOnClick} provider={defaultProvider} />)

    expect(
      screen.getByRole('button', { name: /continue with google/i }),
    ).toBeInTheDocument()
  })

  it('should render correct icon for Google', () => {
    render(<OAuthButton onClick={mockOnClick} provider={defaultProvider} />)

    const button = screen.getByRole('button')
    const icon = button.querySelector('svg')
    expect(icon).toBeInTheDocument()
  })

  it('should render correct icon for GitHub', () => {
    const githubProvider = { icon: 'github', id: 'github', name: 'GitHub' }
    render(<OAuthButton onClick={mockOnClick} provider={githubProvider} />)

    expect(
      screen.getByRole('button', { name: /continue with github/i }),
    ).toBeInTheDocument()
  })

  it('should render correct icon for OIDC', () => {
    const oidcProvider = { icon: 'oidc', id: 'oidc', name: 'OIDC' }
    render(<OAuthButton onClick={mockOnClick} provider={oidcProvider} />)

    expect(
      screen.getByRole('button', { name: /continue with oidc/i }),
    ).toBeInTheDocument()
  })

  it('should call onClick when clicked', async () => {
    const user = userEvent.setup()
    render(<OAuthButton onClick={mockOnClick} provider={defaultProvider} />)

    const button = screen.getByRole('button')
    await user.click(button)

    expect(mockOnClick).toHaveBeenCalledTimes(1)
  })

  it('should be disabled when disabled prop is true', () => {
    render(
      <OAuthButton
        disabled={true}
        onClick={mockOnClick}
        provider={defaultProvider}
      />,
    )

    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
  })

  it('should not call onClick when disabled', async () => {
    const user = userEvent.setup()
    render(
      <OAuthButton
        disabled={true}
        onClick={mockOnClick}
        provider={defaultProvider}
      />,
    )

    const button = screen.getByRole('button')
    await user.click(button)

    expect(mockOnClick).not.toHaveBeenCalled()
  })

  it('should use fallback icon for unknown provider', () => {
    const unknownProvider = { icon: 'unknown', id: 'unknown', name: 'Unknown' }
    render(<OAuthButton onClick={mockOnClick} provider={unknownProvider} />)

    const button = screen.getByRole('button')
    const icon = button.querySelector('svg')
    expect(icon).toBeInTheDocument()
  })
})

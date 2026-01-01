import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { OAuthButton } from './OAuthButton'

describe('OAuthButton', () => {
  const mockOnClick = vi.fn()

  const defaultProvider = {
    id: 'google',
    name: 'Google',
    icon: 'google',
  }

  beforeEach(() => {
    mockOnClick.mockClear()
  })

  it('should render button with provider name', () => {
    render(<OAuthButton provider={defaultProvider} onClick={mockOnClick} />)

    expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument()
  })

  it('should render correct icon for Google', () => {
    render(<OAuthButton provider={defaultProvider} onClick={mockOnClick} />)

    const button = screen.getByRole('button')
    const icon = button.querySelector('svg')
    expect(icon).toBeInTheDocument()
  })

  it('should render correct icon for GitHub', () => {
    const githubProvider = { id: 'github', name: 'GitHub', icon: 'github' }
    render(<OAuthButton provider={githubProvider} onClick={mockOnClick} />)

    expect(screen.getByRole('button', { name: /continue with github/i })).toBeInTheDocument()
  })

  it('should render correct icon for OIDC', () => {
    const oidcProvider = { id: 'oidc', name: 'OIDC', icon: 'oidc' }
    render(<OAuthButton provider={oidcProvider} onClick={mockOnClick} />)

    expect(screen.getByRole('button', { name: /continue with oidc/i })).toBeInTheDocument()
  })

  it('should call onClick when clicked', async () => {
    const user = userEvent.setup()
    render(<OAuthButton provider={defaultProvider} onClick={mockOnClick} />)

    const button = screen.getByRole('button')
    await user.click(button)

    expect(mockOnClick).toHaveBeenCalledTimes(1)
  })

  it('should be disabled when disabled prop is true', () => {
    render(<OAuthButton provider={defaultProvider} onClick={mockOnClick} disabled={true} />)

    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
  })

  it('should not call onClick when disabled', async () => {
    const user = userEvent.setup()
    render(<OAuthButton provider={defaultProvider} onClick={mockOnClick} disabled={true} />)

    const button = screen.getByRole('button')
    await user.click(button)

    expect(mockOnClick).not.toHaveBeenCalled()
  })

  it('should use fallback icon for unknown provider', () => {
    const unknownProvider = { id: 'unknown', name: 'Unknown', icon: 'unknown' }
    render(<OAuthButton provider={unknownProvider} onClick={mockOnClick} />)

    const button = screen.getByRole('button')
    const icon = button.querySelector('svg')
    expect(icon).toBeInTheDocument()
  })
})

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { LocalLoginForm } from './LocalLoginForm'

describe('LocalLoginForm', () => {
  const mockOnSubmit = vi.fn()

  const defaultProps = {
    onSubmit: mockOnSubmit,
    isLoading: false,
  }

  beforeEach(() => {
    mockOnSubmit.mockClear()
  })

  it('should render email and password fields', () => {
    render(<LocalLoginForm {...defaultProps} />)

    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
  })

  it('should render submit button disabled initially', () => {
    render(<LocalLoginForm {...defaultProps} />)

    const submitButton = screen.getByRole('button', { name: /sign in/i })
    expect(submitButton).toBeDisabled()
  })

  it('should enable submit button when email and password are valid', async () => {
    const user = userEvent.setup()
    render(<LocalLoginForm {...defaultProps} />)

    const emailInput = screen.getByLabelText(/email address/i)
    const passwordInput = screen.getByLabelText(/password/i)
    const submitButton = screen.getByRole('button', { name: /sign in/i })

    await user.type(emailInput, 'test@example.com')
    await user.type(passwordInput, 'password123')

    expect(submitButton).toBeEnabled()
  })

  it('should keep submit button disabled with invalid email', async () => {
    const user = userEvent.setup()
    render(<LocalLoginForm {...defaultProps} />)

    const emailInput = screen.getByLabelText(/email address/i)
    const passwordInput = screen.getByLabelText(/password/i)
    const submitButton = screen.getByRole('button', { name: /sign in/i })

    await user.type(emailInput, 'invalid-email')
    await user.type(passwordInput, 'password123')

    expect(submitButton).toBeDisabled()
  })

  it('should show inline validation error for invalid email after blur', async () => {
    const user = userEvent.setup()
    render(<LocalLoginForm {...defaultProps} />)

    const emailInput = screen.getByLabelText(/email address/i)

    await user.type(emailInput, 'invalid-email')
    await user.tab()

    await waitFor(() => {
      expect(screen.getByText(/please enter a valid email address/i)).toBeInTheDocument()
    })
  })

  it('should not show inline validation error before blur', async () => {
    const user = userEvent.setup()
    render(<LocalLoginForm {...defaultProps} />)

    const emailInput = screen.getByLabelText(/email address/i)

    await user.type(emailInput, 'invalid')

    expect(screen.queryByText(/please enter a valid email address/i)).not.toBeInTheDocument()
  })

  it('should highlight email field in red when invalid after blur', async () => {
    const user = userEvent.setup()
    render(<LocalLoginForm {...defaultProps} />)

    const emailInput = screen.getByLabelText(/email address/i)

    await user.type(emailInput, 'invalid-email')
    await user.tab()

    await waitFor(() => {
      expect(emailInput).toHaveClass('border-red-500')
    })
  })

  it('should call onSubmit with email and password on valid submission', async () => {
    const user = userEvent.setup()
    mockOnSubmit.mockResolvedValue(undefined)
    render(<LocalLoginForm {...defaultProps} />)

    const emailInput = screen.getByLabelText(/email address/i)
    const passwordInput = screen.getByLabelText(/password/i)
    const submitButton = screen.getByRole('button', { name: /sign in/i })

    await user.type(emailInput, 'test@example.com')
    await user.type(passwordInput, 'password123')
    await user.click(submitButton)

    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith({
        email: 'test@example.com',
        password: 'password123',
      })
    })
  })

  it('should show validation error if email is empty on submit', async () => {
    const user = userEvent.setup()
    render(<LocalLoginForm {...defaultProps} />)

    const passwordInput = screen.getByLabelText(/password/i)
    await user.type(passwordInput, 'password123')

    const emailInput = screen.getByLabelText(/email address/i)
    await user.click(emailInput)
    await user.tab()

    const form = emailInput.closest('form')!
    await user.click(form)

    expect(mockOnSubmit).not.toHaveBeenCalled()
  })

  it('should display error message from props', () => {
    render(<LocalLoginForm {...defaultProps} error="Invalid credentials" />)

    expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument()
  })

  it('should disable inputs when isLoading is true', () => {
    render(<LocalLoginForm {...defaultProps} isLoading={true} />)

    const emailInput = screen.getByLabelText(/email address/i)
    const passwordInput = screen.getByLabelText(/password/i)

    expect(emailInput).toBeDisabled()
    expect(passwordInput).toBeDisabled()
  })

  it('should show "Signing in..." text when loading', () => {
    render(<LocalLoginForm {...defaultProps} isLoading={true} />)

    expect(screen.getByText(/signing in\.\.\./i)).toBeInTheDocument()
  })

  it('should trim whitespace from email before submission', async () => {
    const user = userEvent.setup()
    mockOnSubmit.mockResolvedValue(undefined)
    render(<LocalLoginForm {...defaultProps} />)

    const emailInput = screen.getByLabelText(/email address/i)
    const passwordInput = screen.getByLabelText(/password/i)
    const submitButton = screen.getByRole('button', { name: /sign in/i })

    await user.type(emailInput, '  test@example.com  ')
    await user.type(passwordInput, 'password123')
    await user.click(submitButton)

    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith({
        email: 'test@example.com',
        password: 'password123',
      })
    })
  })

  it('should accept various valid email formats', async () => {
    const validEmails = [
      'test@example.com',
      'user+tag@domain.co.uk',
      'name.surname@company.org',
      'a@b.c',
    ]

    for (const email of validEmails) {
      const user = userEvent.setup()
      const { unmount } = render(<LocalLoginForm {...defaultProps} />)

      const emailInput = screen.getByLabelText(/email address/i)
      const passwordInput = screen.getByLabelText(/password/i)

      await user.type(emailInput, email)
      await user.type(passwordInput, 'password')

      const submitButton = screen.getByRole('button', { name: /sign in/i })
      expect(submitButton).toBeEnabled()

      unmount()
    }
  })
})

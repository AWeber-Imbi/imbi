import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface LocalLoginFormProps {
  error?: string
  initialEmail?: string
  isLoading: boolean
  onSubmit: (credentials: { email: string; password: string }) => Promise<void>
}

export function LocalLoginForm({
  error,
  initialEmail = '',
  isLoading,
  onSubmit,
}: LocalLoginFormProps) {
  const [email, setEmail] = useState(initialEmail)
  const [password, setPassword] = useState('')
  const [validationError, setValidationError] = useState('')
  const [emailTouched, setEmailTouched] = useState(false)

  // Clear password on login error, but keep email
  useEffect(() => {
    if (error) {
      setPassword('')
    }
  }, [error])

  const isValidEmail = (email: string) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
  }

  const emailIsInvalid =
    emailTouched && email.trim() && !isValidEmail(email.trim())
  const canSubmit =
    email.trim() && password && isValidEmail(email.trim()) && !isLoading

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!email.trim()) {
      setValidationError('Email address is required')
      return
    }

    if (!isValidEmail(email.trim())) {
      setValidationError('Please enter a valid email address')
      return
    }

    if (!password) {
      setValidationError('Password is required')
      return
    }

    setValidationError('')

    try {
      await onSubmit({ email: email.trim(), password })
    } catch (_err) {
      // Error handling done by parent
    }
  }

  const displayError = validationError || error

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      {displayError && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg
                className="h-5 w-5 text-red-400"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  clipRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  fillRule="evenodd"
                />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm font-medium text-red-800">{displayError}</p>
            </div>
          </div>
        </div>
      )}

      <div>
        <label className="mb-1.5 block text-sm text-gray-700" htmlFor="email">
          Email Address
        </label>
        <Input
          autoComplete="email"
          autoFocus
          className={
            emailIsInvalid ? 'border-red-500 focus-visible:ring-red-500' : ''
          }
          disabled={isLoading}
          id="email"
          onBlur={() => setEmailTouched(true)}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Enter your email address"
          type="email"
          value={email}
        />
        {emailIsInvalid && (
          <p className="mt-1 text-sm text-red-600">
            Please enter a valid email address
          </p>
        )}
      </div>

      <div>
        <label
          className="mb-1.5 block text-sm text-gray-700"
          htmlFor="password"
        >
          Password
        </label>
        <Input
          autoComplete="current-password"
          disabled={isLoading}
          id="password"
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Enter your password"
          type="password"
          value={password}
        />
      </div>

      <Button
        className="w-full bg-action text-action-foreground hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!canSubmit}
        type="submit"
      >
        {isLoading ? 'Signing in...' : 'Sign In'}
      </Button>
    </form>
  )
}

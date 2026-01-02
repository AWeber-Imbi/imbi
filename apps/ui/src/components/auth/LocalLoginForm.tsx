import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface LocalLoginFormProps {
  onSubmit: (credentials: { email: string; password: string }) => Promise<void>
  isLoading: boolean
  error?: string
  initialEmail?: string
}

export function LocalLoginForm({ onSubmit, isLoading, error, initialEmail = '' }: LocalLoginFormProps) {
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

  const emailIsInvalid = emailTouched && email.trim() && !isValidEmail(email.trim())
  const canSubmit = email.trim() && password && isValidEmail(email.trim()) && !isLoading

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
    } catch (err) {
      // Error handling done by parent
    }
  }

  const displayError = validationError || error

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {displayError && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm font-medium text-red-800">
                {displayError}
              </p>
            </div>
          </div>
        </div>
      )}

      <div>
        <label htmlFor="email" className="block text-sm mb-1.5 text-gray-700">
          Email Address
        </label>
        <Input
          id="email"
          type="email"
          placeholder="Enter your email address"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onBlur={() => setEmailTouched(true)}
          disabled={isLoading}
          autoComplete="email"
          autoFocus
          className={emailIsInvalid ? 'border-red-500 focus-visible:ring-red-500' : ''}
        />
        {emailIsInvalid && (
          <p className="mt-1 text-sm text-red-600">
            Please enter a valid email address
          </p>
        )}
      </div>

      <div>
        <label htmlFor="password" className="block text-sm mb-1.5 text-gray-700">
          Password
        </label>
        <Input
          id="password"
          type="password"
          placeholder="Enter your password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={isLoading}
          autoComplete="current-password"
        />
      </div>

      <Button
        type="submit"
        className="w-full bg-[#2A4DD0] hover:bg-blue-700 text-white disabled:opacity-50 disabled:cursor-not-allowed"
        disabled={!canSubmit}
      >
        {isLoading ? 'Signing in...' : 'Sign In'}
      </Button>
    </form>
  )
}

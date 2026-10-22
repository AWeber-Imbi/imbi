import { useState } from 'react'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface MfaCodeFormProps {
  error?: string
  isLoading: boolean
  onCancel: () => void
  onSubmit: (code: string) => Promise<void>
}

// Second login step for users with MFA on. Takes a TOTP code from the
// authenticator app or one of the 8-character backup codes.
export function MfaCodeForm({
  error,
  isLoading,
  onCancel,
  onSubmit,
}: MfaCodeFormProps) {
  const [code, setCode] = useState('')
  const trimmed = code.trim()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    await onSubmit(trimmed)
  }

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      {error && <Alert variant="danger">{error}</Alert>}
      <div>
        <Label className="mb-1.5 block text-sm" htmlFor="mfa-code">
          Authentication code
        </Label>
        <Input
          autoComplete="one-time-code"
          autoFocus
          disabled={isLoading}
          id="mfa-code"
          onChange={(e) => setCode(e.target.value)}
          placeholder="123456"
          value={code}
        />
        <p className="text-tertiary mt-1 text-xs">
          Enter the code from your authenticator app, or a backup code.
        </p>
      </div>
      <Button
        className="bg-action text-action-foreground hover:bg-action-hover w-full disabled:cursor-not-allowed disabled:opacity-50"
        disabled={trimmed.length < 6 || isLoading}
        type="submit"
      >
        {isLoading ? 'Verifying...' : 'Verify'}
      </Button>
      <Button
        className="w-full"
        disabled={isLoading}
        onClick={onCancel}
        type="button"
        variant="ghost"
      >
        Back
      </Button>
    </form>
  )
}

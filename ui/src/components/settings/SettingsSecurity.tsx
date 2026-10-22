import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { disableMfa, getMfaStatus, setupMfa, verifyMfa } from '@/api/endpoints'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { MfaSetup } from '@/types'

const MFA_STATUS_KEY = ['mfa-status']

export function SettingsSecurity() {
  return (
    <Card className="p-8" style={{ borderWidth: '0.5px' }}>
      <h2 className="text-primary mb-6 text-[18px] font-medium">
        Security settings
      </h2>

      <div className="space-y-6">
        {/* Authentication */}
        <div>
          <h3 className="text-primary mb-4 text-[16px] font-medium">
            Authentication
          </h3>
          <TwoFactorSection />
        </div>

        <Separator />

        {/* Session management */}
        <div>
          <h3 className="text-primary mb-4 text-[16px] font-medium">
            Session management
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-primary text-[13.5px]">
                  Auto-logout on inactivity
                </p>
                <p className="text-tertiary text-[12px]">
                  Automatically sign out after 30 minutes of inactivity
                </p>
              </div>
              <Switch defaultChecked />
            </div>
            <Button
              className=""
              style={{ borderWidth: '0.5px' }}
              variant="outline"
            >
              View active sessions
            </Button>
          </div>
        </div>

        <Separator />

        {/* Access logs */}
        <div>
          <h3 className="text-primary mb-4 text-[16px] font-medium">
            Access logs
          </h3>
          <p className="text-tertiary mb-4 text-[12px]">
            View a history of access to your account
          </p>
          <Button
            className=""
            style={{ borderWidth: '0.5px' }}
            variant="outline"
          >
            View access logs
          </Button>
        </div>
      </div>
    </Card>
  )
}

// Enrollment: POST /mfa/setup returns the secret, QR code and backup codes;
// MFA stays off until POST /mfa/verify accepts a code from the app.
function TwoFactorSection() {
  const queryClient = useQueryClient()
  const [setup, setSetup] = useState<MfaSetup | null>(null)
  const [disabling, setDisabling] = useState(false)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')

  const { data: status, isLoading } = useQuery({
    queryFn: ({ signal }) => getMfaStatus(signal),
    queryKey: MFA_STATUS_KEY,
  })

  const reset = () => {
    setSetup(null)
    setDisabling(false)
    setCode('')
    setError('')
  }

  const setupMutation = useMutation({
    mutationFn: setupMfa,
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: (data) => {
      reset()
      setSetup(data)
    },
  })

  const verifyMutation = useMutation({
    mutationFn: () => verifyMfa(code.trim()),
    onError: (err) => setError(extractApiErrorDetail(err)),
    onSuccess: () => {
      reset()
      toast.success('Two-factor authentication is on')
      void queryClient.invalidateQueries({ queryKey: MFA_STATUS_KEY })
    },
  })

  const disableMutation = useMutation({
    mutationFn: () =>
      disableMfa(
        status?.has_password
          ? { current_password: code }
          : { mfa_code: code.trim() },
      ),
    onError: (err) => setError(extractApiErrorDetail(err)),
    onSuccess: () => {
      reset()
      toast.success('Two-factor authentication is off')
      void queryClient.invalidateQueries({ queryKey: MFA_STATUS_KEY })
    },
  })

  if (isLoading || !status) {
    return <p className="text-tertiary text-[12px]">Loading...</p>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-primary text-[13.5px]">
            Two-factor authentication
          </p>
          <p className="text-tertiary text-[12px]">
            {status.enabled
              ? `${status.backup_codes_remaining} backup codes left`
              : 'Ask for a code from an authenticator app when you sign in with a password'}
          </p>
        </div>
        {status.enabled ? (
          <div className="flex items-center gap-2">
            <Badge style={{ borderWidth: '0.5px' }} variant="success">
              On
            </Badge>
            {!disabling && (
              <Button
                onClick={() => {
                  reset()
                  setDisabling(true)
                }}
                size="sm"
                style={{ borderWidth: '0.5px' }}
                variant="outline"
              >
                Turn off
              </Button>
            )}
          </div>
        ) : (
          !setup && (
            <Button
              disabled={setupMutation.isPending}
              onClick={() => setupMutation.mutate()}
              size="sm"
              style={{ borderWidth: '0.5px' }}
              variant="outline"
            >
              Set up
            </Button>
          )
        )}
      </div>

      {setup && (
        <form
          className="bg-secondary/50 space-y-4 rounded-lg p-4"
          onSubmit={(e) => {
            e.preventDefault()
            verifyMutation.mutate()
          }}
        >
          <p className="text-primary text-[13.5px]">
            1. Scan the QR code with your authenticator app, or enter the key.
          </p>
          <img
            alt="MFA QR code"
            className="size-40 rounded bg-white"
            src={`data:image/png;base64,${setup.qr_code}`}
          />
          <p className="text-secondary font-mono text-[12px] break-all">
            {setup.secret}
          </p>
          <Alert title="2. Save your backup codes" variant="warning">
            Each code signs you in once if you lose your device. They are not
            shown again.
            <ul className="mt-2 grid grid-cols-2 gap-1 font-mono">
              {setup.backup_codes.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </Alert>
          <div>
            <Label className="mb-1.5 block text-[13.5px]" htmlFor="mfa-verify">
              3. Enter the code from the app
            </Label>
            <Input
              autoComplete="one-time-code"
              id="mfa-verify"
              onChange={(e) => setCode(e.target.value)}
              value={code}
            />
          </div>
          {error && <Alert variant="danger">{error}</Alert>}
          <div className="flex gap-2">
            <Button
              disabled={code.trim().length < 6 || verifyMutation.isPending}
              type="submit"
            >
              Turn on
            </Button>
            <Button onClick={reset} type="button" variant="ghost">
              Cancel
            </Button>
          </div>
        </form>
      )}

      {disabling && (
        <form
          className="bg-secondary/50 space-y-4 rounded-lg p-4"
          onSubmit={(e) => {
            e.preventDefault()
            disableMutation.mutate()
          }}
        >
          <div>
            <Label className="mb-1.5 block text-[13.5px]" htmlFor="mfa-confirm">
              {status.has_password
                ? 'Enter your password to turn off two-factor authentication'
                : 'Enter a code from your authenticator app, or a backup code'}
            </Label>
            <Input
              autoComplete={
                status.has_password ? 'current-password' : 'one-time-code'
              }
              id="mfa-confirm"
              onChange={(e) => setCode(e.target.value)}
              type={status.has_password ? 'password' : 'text'}
              value={code}
            />
          </div>
          {error && <Alert variant="danger">{error}</Alert>}
          <div className="flex gap-2">
            <Button
              disabled={!code || disableMutation.isPending}
              type="submit"
              variant="destructive"
            >
              Turn off
            </Button>
            <Button onClick={reset} type="button" variant="ghost">
              Cancel
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}

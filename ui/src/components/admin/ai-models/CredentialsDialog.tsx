import { useState } from 'react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import type { AIProvider } from '@/types'

interface CredentialsDialogProps {
  error?: unknown
  isPending: boolean
  onClose: () => void
  onRemove: () => void
  onSave: (apiKey: string) => void
  open: boolean
  provider: AIProvider
}

export function CredentialsDialog({
  error,
  isPending,
  onClose,
  onRemove,
  onSave,
  open,
  provider,
}: CredentialsDialogProps) {
  const [apiKey, setApiKey] = useState('')
  const usesIam = provider.auth_kind === 'iam'

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      open={open}
    >
      <DialogContent className="max-w-140">
        <DialogHeader>
          <DialogTitle>{provider.name} credentials</DialogTitle>
          <DialogDescription>
            Stored encrypted and shared by every model under this provider.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 p-6">
          {error != null && (
            <ErrorBanner error={error} title="Failed to update credentials" />
          )}
          {usesIam && (
            <div className="border-tertiary bg-secondary rounded-md border p-3">
              <div className="text-primary text-sm font-medium">
                Currently authenticating with an IAM role
              </div>
              <p className="text-tertiary mt-1 text-sm">
                Setting a static key here overrides the role for every model
                under {provider.name}.
              </p>
            </div>
          )}
          <FormField
            description={
              provider.has_credentials
                ? `Replacing the key takes effect on the next request from every model under ${provider.name}.`
                : 'No key is set, so models under this provider cannot be called.'
            }
            htmlFor="ai-provider-key"
            label="API key"
          >
            <Input
              autoComplete="new-password"
              className="font-mono"
              id="ai-provider-key"
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Paste a key to set credentials"
              type="password"
              value={apiKey}
            />
          </FormField>
          {provider.has_credentials && provider.credential_hint && (
            <p className="text-tertiary font-mono text-xs">
              Current key ends in ••••{provider.credential_hint}
            </p>
          )}
        </div>

        <DialogFooter>
          {provider.has_credentials && (
            <button
              className="text-destructive mr-auto text-sm font-medium"
              disabled={isPending}
              onClick={onRemove}
              type="button"
            >
              Remove key
            </button>
          )}
          <button
            className="text-secondary hover:text-primary text-sm font-medium"
            onClick={onClose}
            type="button"
          >
            Cancel
          </button>
          <button
            className="bg-action text-action-foreground hover:bg-action-hover rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50"
            disabled={isPending || apiKey.trim() === ''}
            onClick={() => onSave(apiKey.trim())}
            type="button"
          >
            Save key
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

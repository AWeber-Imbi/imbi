import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import { listTokenExchangers } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
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
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import { parseObject } from '@/lib/utils'
import type { AIProvider } from '@/types'

interface CredentialsDialogProps {
  error?: unknown
  isPending: boolean
  onClose: () => void
  onRemove: () => void
  onRemoveWorkloadIdentity: () => void
  onSave: (apiKey: string) => void
  onSaveWorkloadIdentity: (body: {
    organization: string
    target: Record<string, unknown>
  }) => void
  open: boolean
  provider: AIProvider
}

export function CredentialsDialog({
  error,
  isPending,
  onClose,
  onRemove,
  onRemoveWorkloadIdentity,
  onSave,
  onSaveWorkloadIdentity,
  open,
  provider,
}: CredentialsDialogProps) {
  const [apiKey, setApiKey] = useState('')
  const [targetText, setTargetText] = useState('')
  const [confirmingRemove, setConfirmingRemove] = useState(false)
  const { organizations, selectedOrganization } = useOrganization()
  const usesIam = provider.auth_kind === 'iam'
  const wif = provider.workload_identity ?? null
  const orgSlug = selectedOrganization?.slug
  // WIF plan 4.6 and D8: only a driver with an installed token
  // exchanger, on the default endpoint.
  const exchangersQuery = useQuery({
    enabled: open && !!orgSlug,
    queryFn: ({ signal }) => listTokenExchangers(orgSlug ?? '', signal),
    queryKey: ['token-exchangers', orgSlug],
  })
  const exchanger = exchangersQuery.data?.find(
    (e) => e.vendor === provider.driver,
  )
  const wifEligible = !wif && !provider.base_url && !provider.has_credentials
  const canUseWif = !!exchanger && wifEligible
  // A 403 means no read access to the exchangers, which is expected.
  const exchangersFailed =
    wifEligible &&
    exchangersQuery.isError &&
    !(
      exchangersQuery.error instanceof ApiError &&
      exchangersQuery.error.status === 403
    )
  let target: null | Record<string, unknown> = null
  let targetError: null | string = null
  if (targetText.trim()) {
    try {
      target = parseObject('The target', targetText)
    } catch (err) {
      targetError = (err as Error).message
    }
  }
  const wifOrg = wif
    ? (organizations.find((o) => o.id === wif.organization_id)?.name ??
      wif.organization_id)
    : null

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
          {wif && (
            <div className="border-tertiary bg-secondary rounded-md border p-3">
              <div className="text-primary text-sm font-medium">
                Authenticating with workload identity
              </div>
              <p className="text-tertiary mt-1 text-sm">
                imbi-api gets a short-lived token with the identity source of{' '}
                {wifOrg}. There is no stored key.
              </p>
              <pre className="text-tertiary mt-2 font-mono text-xs whitespace-pre-wrap">
                {JSON.stringify(wif.target)}
              </pre>
            </div>
          )}
          {!wif && (
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
          )}
          {provider.has_credentials && provider.credential_hint && (
            <p className="text-tertiary font-mono text-xs">
              Current key ends in ••••{provider.credential_hint}
            </p>
          )}
          {exchangersFailed && (
            <p className="text-danger flex items-center gap-2 text-xs">
              Could not load the workload identity vendors.
              <Button
                onClick={() => void exchangersQuery.refetch()}
                size="sm"
                variant="ghost"
              >
                Retry
              </Button>
            </p>
          )}
          {canUseWif && selectedOrganization && (
            <FormField
              description={`Instead of a key: a short-lived token from the identity source of ${selectedOrganization.name} (Admin, Secrets, Identity). The vendor ids: ${exchanger?.target_help ?? ''}`}
              error={targetError ?? undefined}
              htmlFor="ai-provider-wif-target"
              label="Workload identity target"
              touched
            >
              <Textarea
                className="font-mono"
                id="ai-provider-wif-target"
                onChange={(e) => setTargetText(e.target.value)}
                placeholder="{}"
                value={targetText}
              />
            </FormField>
          )}
        </div>

        <DialogFooter>
          {wif && (
            <button
              className="text-destructive mr-auto text-sm font-medium"
              disabled={isPending}
              onClick={onRemoveWorkloadIdentity}
              type="button"
            >
              Stop using workload identity
            </button>
          )}
          {provider.has_credentials && (
            <button
              className="text-destructive mr-auto text-sm font-medium"
              disabled={isPending}
              onClick={() => setConfirmingRemove(true)}
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
          {canUseWif && selectedOrganization && (
            <button
              className="border-tertiary text-primary rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-50"
              disabled={isPending || target === null}
              onClick={() =>
                target &&
                onSaveWorkloadIdentity({
                  organization: selectedOrganization.slug,
                  target,
                })
              }
              type="button"
            >
              Use workload identity
            </button>
          )}
          {!wif && (
            <button
              className="bg-action text-action-foreground hover:bg-action-hover rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50"
              disabled={isPending || apiKey.trim() === ''}
              onClick={() => onSave(apiKey.trim())}
              type="button"
            >
              Save key
            </button>
          )}
        </DialogFooter>
      </DialogContent>

      <ConfirmDialog
        confirmLabel="Remove"
        description={`Models under ${provider.name} cannot be called until a new key is set.`}
        onCancel={() => setConfirmingRemove(false)}
        onConfirm={() => {
          setConfirmingRemove(false)
          onRemove()
        }}
        open={confirmingRemove}
        title={`Remove the ${provider.name} key?`}
      />
    </Dialog>
  )
}

import { useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle,
  Copy,
  Lock,
  Power,
  Settings,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import { API_BASE_URL } from '@/api/client'
import {
  createAuthProvider,
  deleteAuthProvider,
  getLocalAuthConfig,
  listAuthProviders,
  updateAuthProvider,
  updateLocalAuthConfig,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import { Switch } from '@/components/ui/switch'
import { useAuth } from '@/hooks/useAuth'
import { extractApiErrorDetail } from '@/lib/apiError'
import type {
  LocalAuthConfig,
  LoginProviderCreate,
  LoginProviderRead,
  LoginProviderUpdate,
  OAuthAppType,
} from '@/types'

const APP_TYPE_DESCRIPTIONS: Record<OAuthAppType, string> = {
  github:
    'Sign in with a GitHub account. Requires client ID and secret from a GitHub OAuth App.',
  google:
    'Sign in with a Google Workspace account. Optionally restrict by email domain.',
  oidc: 'Generic OpenID Connect provider. Requires an issuer URL and a registered client.',
}

const APP_TYPE_ORDER: OAuthAppType[] = ['google', 'github', 'oidc']

const callbackUrlForType = (appType: OAuthAppType): string =>
  `${API_BASE_URL}/auth/oauth/${appType}/callback`

const copyToClipboard = async (value: string, label: string) => {
  try {
    await navigator.clipboard.writeText(value)
    toast.success(`${label} copied`)
  } catch {
    toast.error(`Failed to copy ${label.toLowerCase()}`)
  }
}

const sortProviders = (rows: LoginProviderRead[]): LoginProviderRead[] => {
  const rank = (p: LoginProviderRead): number => {
    const t = p.oauth_app_type
    return t ? APP_TYPE_ORDER.indexOf(t) : APP_TYPE_ORDER.length
  }
  return [...rows].sort((a, b) => {
    const r = rank(a) - rank(b)
    if (r !== 0) return r
    return a.slug.localeCompare(b.slug)
  })
}

interface CreateDialogProps {
  isSaving: boolean
  onCancel: () => void
  onSave: (payload: LoginProviderCreate) => void
}

interface EditDialogProps {
  isSaving: boolean
  onCancel: () => void
  onSave: (payload: LoginProviderUpdate) => void
  provider: LoginProviderRead
}

export function AuthProvidersManagement() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const canWrite =
    !!user?.is_admin ||
    (user?.permissions ?? []).includes('auth_providers:write')

  const [editing, setEditing] = useState<LoginProviderRead | null>(null)
  const [creating, setCreating] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<LoginProviderRead | null>(
    null,
  )

  const { data, error, isLoading } = useQuery({
    queryFn: ({ signal }) => listAuthProviders(signal),
    queryKey: ['admin', 'auth-providers'],
  })

  const localAuthQuery = useQuery({
    queryFn: ({ signal }) => getLocalAuthConfig(signal),
    queryKey: ['admin', 'local-auth'],
  })

  const localAuthMutation = useMutation({
    mutationFn: (enabled: boolean) => updateLocalAuthConfig({ enabled }),
    onError: (err) => {
      toast.error(
        `Failed to update local authentication: ${extractApiErrorDetail(err)}`,
      )
      queryClient.invalidateQueries({ queryKey: ['admin', 'local-auth'] })
    },
    onMutate: async (enabled: boolean) => {
      await queryClient.cancelQueries({ queryKey: ['admin', 'local-auth'] })
      const previous = queryClient.getQueryData<LocalAuthConfig>([
        'admin',
        'local-auth',
      ])
      if (previous) {
        queryClient.setQueryData<LocalAuthConfig>(['admin', 'local-auth'], {
          ...previous,
          enabled,
        })
      }
      return { previous }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'local-auth'] })
      queryClient.invalidateQueries({ queryKey: ['authProviders'] })
      toast.success('Local authentication updated')
    },
  })

  const providers = useMemo(() => sortProviders(data ?? []), [data])

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['admin', 'auth-providers'] })
    queryClient.invalidateQueries({ queryKey: ['authProviders'] })
  }

  const createMutation = useMutation({
    mutationFn: (payload: LoginProviderCreate) => createAuthProvider(payload),
    onError: (err) => {
      toast.error(
        `Failed to create auth provider: ${extractApiErrorDetail(err)}`,
      )
    },
    onSuccess: () => {
      invalidateAll()
      setCreating(false)
      toast.success('Auth provider created')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      payload,
      slug,
    }: {
      payload: LoginProviderUpdate
      slug: string
    }) => updateAuthProvider(slug, payload),
    onError: (err) => {
      toast.error(
        `Failed to update auth provider: ${extractApiErrorDetail(err)}`,
      )
    },
    onSuccess: () => {
      invalidateAll()
      setEditing(null)
      toast.success('Auth provider updated')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => deleteAuthProvider(slug),
    onError: (err) => {
      toast.error(
        `Failed to delete auth provider: ${extractApiErrorDetail(err)}`,
      )
    },
    onSuccess: () => {
      invalidateAll()
      setPendingDelete(null)
      toast.success('Auth provider deleted')
    },
  })

  if (isLoading) {
    return <LoadingState label="Loading auth providers..." />
  }

  if (error) {
    return <ErrorBanner error={error} title="Failed to load auth providers" />
  }

  return (
    <div className="space-y-4">
      {!canWrite && (
        <div
          className={
            'flex items-start gap-3 rounded-lg border border-info bg-info p-4'
          }
        >
          <Power className="mt-0.5 h-5 w-5 flex-shrink-0 text-info" />
          <p className="text-sm text-info">
            You don't have permission to modify auth providers. Contact an
            administrator to add or change providers.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="flex h-full flex-col">
          <CardHeader
            className={
              'flex flex-row items-center justify-between space-y-0 pb-2'
            }
          >
            <div className="flex items-center gap-2">
              <Lock className="h-5 w-5 text-secondary" />
              <CardTitle>Local Authentication</CardTitle>
            </div>
            {localAuthQuery.data?.enabled ? (
              <CheckCircle className="h-5 w-5 flex-shrink-0 text-status-review-dot" />
            ) : (
              <AlertCircle className="h-5 w-5 flex-shrink-0 text-tertiary" />
            )}
          </CardHeader>
          <CardContent className="flex flex-1 flex-col space-y-3">
            <p className="text-xs text-tertiary">
              Allow users to sign in with an email address and password stored
              in Imbi.
            </p>
            <div className="mt-auto flex items-center justify-between rounded-lg border border-input p-3">
              <div>
                <div className="text-sm text-primary">Enabled</div>
                <div className="text-xs text-tertiary">
                  When disabled, the email/password form is hidden on the login
                  page.
                </div>
              </div>
              <Switch
                checked={localAuthQuery.data?.enabled ?? false}
                disabled={
                  !canWrite ||
                  localAuthQuery.isLoading ||
                  localAuthMutation.isPending
                }
                onCheckedChange={(checked) => localAuthMutation.mutate(checked)}
              />
            </div>
          </CardContent>
        </Card>

        {providers.map((provider) => {
          const appType = provider.oauth_app_type
          const typeDesc = appType
            ? APP_TYPE_DESCRIPTIONS[appType]
            : 'Login-eligible service application.'
          const isActive = provider.status === 'active'
          return (
            <Card key={provider.slug}>
              <CardHeader
                className={
                  'flex flex-row items-center justify-between space-y-0 pb-2'
                }
              >
                <div className="flex items-center gap-2">
                  <CardTitle>{provider.name}</CardTitle>
                </div>
                {isActive ? (
                  <CheckCircle className="h-5 w-5 flex-shrink-0 text-status-review-dot" />
                ) : (
                  <AlertCircle className="h-5 w-5 flex-shrink-0 text-tertiary" />
                )}
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-tertiary">{typeDesc}</p>
                <div>
                  <div className="mb-1 text-xs text-tertiary">
                    Authorized redirect URI
                  </div>
                  <div
                    className={
                      'flex items-center gap-1 rounded-md border border-input bg-secondary px-2 py-1'
                    }
                  >
                    <code
                      className="flex-1 truncate text-xs text-secondary"
                      title={provider.callback_url}
                    >
                      {provider.callback_url}
                    </code>
                    <Button
                      aria-label="Copy redirect URI"
                      className="h-6 w-6 flex-shrink-0"
                      onClick={() =>
                        copyToClipboard(provider.callback_url, 'Redirect URI')
                      }
                      size="icon"
                      type="button"
                      variant="ghost"
                    >
                      <Copy className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
                {canWrite && (
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Button
                      onClick={() => setEditing(provider)}
                      size="sm"
                      variant="outline"
                    >
                      <Settings className="mr-1 h-4 w-4" />
                      Edit
                    </Button>
                    <Button
                      onClick={() => setPendingDelete(provider)}
                      size="sm"
                      variant="ghost"
                    >
                      <Trash2 className="mr-1 h-4 w-4" />
                      Delete
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}

        {canWrite && (
          <Card
            className="flex items-center justify-center border-dashed bg-transparent"
            onClick={() => setCreating(true)}
            role="button"
            tabIndex={0}
          >
            <CardContent className="flex h-full w-full items-center justify-center p-6">
              <Button
                onClick={() => setCreating(true)}
                type="button"
                variant="outline"
              >
                + Add auth provider
              </Button>
            </CardContent>
          </Card>
        )}
      </div>

      {creating && (
        <AuthProviderCreateDialog
          isSaving={createMutation.isPending}
          onCancel={() => setCreating(false)}
          onSave={(payload) => createMutation.mutate(payload)}
        />
      )}

      {editing && (
        <AuthProviderEditDialog
          isSaving={updateMutation.isPending}
          onCancel={() => setEditing(null)}
          onSave={(payload) =>
            updateMutation.mutate({ payload, slug: editing.slug })
          }
          provider={editing}
        />
      )}

      <ConfirmDialog
        confirmLabel="Delete"
        description="Users currently linked through this provider won't be able to sign in until it's recreated."
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.slug)
        }}
        open={!!pendingDelete}
        title={
          pendingDelete ? `Remove the ${pendingDelete.name} Auth Provider?` : ''
        }
      />
    </div>
  )
}

function AuthProviderCreateDialog({
  isSaving,
  onCancel,
  onSave,
}: CreateDialogProps) {
  const [appType, setAppType] = useState<OAuthAppType>('google')
  const [clientId, setClientId] = useState('')
  const [secret, setSecret] = useState('')
  const [issuerUrl, setIssuerUrl] = useState('')
  const [scopes, setScopes] = useState('')
  const [allowedDomains, setAllowedDomains] = useState<string[]>([])
  const [domainDraft, setDomainDraft] = useState('')
  const [enableIntegration, setEnableIntegration] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const showAllowedDomains = appType === 'google'
  const showIssuerUrl = appType === 'oidc'
  const callbackUrl = callbackUrlForType(appType)

  const addDomain = () => {
    const value = domainDraft.trim().toLowerCase()
    if (!value) return
    if (!allowedDomains.includes(value)) {
      setAllowedDomains([...allowedDomains, value])
    }
    setDomainDraft('')
  }

  const removeDomain = (value: string) => {
    setAllowedDomains(allowedDomains.filter((d) => d !== value))
  }

  const validate = (): boolean => {
    const next: Record<string, string> = {}
    if (!clientId.trim()) next.client_id = 'Client ID is required'
    if (!secret) next.client_secret = 'Client secret is required'
    if (showIssuerUrl) {
      if (!issuerUrl.trim()) {
        next.issuer_url = 'Issuer URL is required for OIDC'
      } else {
        try {
          const u = new URL(issuerUrl.trim())
          if (u.protocol !== 'https:') {
            next.issuer_url = 'Issuer URL must be https://'
          }
        } catch {
          next.issuer_url = 'Issuer URL must be a valid URL'
        }
      }
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    const payload: LoginProviderCreate = {
      client_id: clientId.trim(),
      client_secret: secret,
      oauth_app_type: appType,
      usage: enableIntegration ? 'both' : 'login',
    }
    if (showIssuerUrl && issuerUrl.trim()) {
      payload.issuer_url = issuerUrl.trim()
    }
    if (showAllowedDomains && allowedDomains.length > 0) {
      payload.allowed_domains = allowedDomains
    }
    if (scopes.trim()) {
      payload.scopes = scopes
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    }
    onSave(payload)
  }

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
      open
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add auth provider</DialogTitle>
          <DialogDescription>
            Configure a new login provider backed by a service application.
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              OAuth Type <span className="text-red-500">*</span>
            </label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
              disabled={isSaving}
              onChange={(e) => setAppType(e.target.value as OAuthAppType)}
              value={appType}
            >
              <option value="google">Google</option>
              <option value="github">GitHub</option>
              <option value="oidc">OpenID Connect</option>
            </select>
          </div>

          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              Redirect URL
            </label>
            <div className="flex items-center gap-2">
              <Input
                className="flex-1 font-mono text-xs"
                readOnly
                value={callbackUrl}
              />
              <Button
                aria-label="Copy redirect URL"
                onClick={() => copyToClipboard(callbackUrl, 'Redirect URL')}
                size="icon"
                type="button"
                variant="outline"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
            <p className="mt-1 text-xs text-tertiary">
              Configure this URL in the provider&apos;s OAuth app settings.
            </p>
          </div>

          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              Client ID <span className="text-red-500">*</span>
            </label>
            <Input
              disabled={isSaving}
              onChange={(e) => setClientId(e.target.value)}
              value={clientId}
            />
            {errors.client_id && (
              <div className="mt-1 text-xs text-danger">{errors.client_id}</div>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              Client Secret <span className="text-red-500">*</span>
            </label>
            <Input
              autoComplete="new-password"
              disabled={isSaving}
              onChange={(e) => setSecret(e.target.value)}
              type="password"
              value={secret}
            />
            {errors.client_secret && (
              <div className="mt-1 text-xs text-danger">
                {errors.client_secret}
              </div>
            )}
          </div>

          {showIssuerUrl && (
            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Issuer URL <span className="text-red-500">*</span>
              </label>
              <Input
                disabled={isSaving}
                onChange={(e) => setIssuerUrl(e.target.value)}
                placeholder="https://idp.example.com/"
                value={issuerUrl}
              />
              {errors.issuer_url && (
                <div className="mt-1 text-xs text-danger">
                  {errors.issuer_url}
                </div>
              )}
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              Scopes
            </label>
            <Input
              disabled={isSaving}
              onChange={(e) => setScopes(e.target.value)}
              placeholder="openid, email, profile (comma-separated)"
              value={scopes}
            />
          </div>

          {showAllowedDomains && (
            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Allowed Email Domains
              </label>
              <div
                className={
                  'flex flex-wrap items-center gap-2 rounded-lg border border-input bg-background p-2'
                }
              >
                {allowedDomains.map((d) => (
                  <span
                    className={
                      'inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary'
                    }
                    key={d}
                  >
                    {d}
                    <button
                      aria-label={`Remove ${d}`}
                      className="text-tertiary hover:text-primary"
                      disabled={isSaving}
                      onClick={() => removeDomain(d)}
                      onMouseDown={(e) => e.preventDefault()}
                      type="button"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                <input
                  className={
                    'min-w-[8rem] flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-muted-foreground'
                  }
                  disabled={isSaving}
                  onBlur={addDomain}
                  onChange={(e) => setDomainDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ',' || e.key === ' ') {
                      e.preventDefault()
                      addDomain()
                    } else if (
                      e.key === 'Backspace' &&
                      !domainDraft &&
                      allowedDomains.length > 0
                    ) {
                      setAllowedDomains(allowedDomains.slice(0, -1))
                    }
                  }}
                  placeholder={
                    allowedDomains.length === 0
                      ? 'example.com (Enter to add)'
                      : ''
                  }
                  value={domainDraft}
                />
              </div>
            </div>
          )}

          <label className="flex w-full items-center gap-2 text-sm text-secondary">
            <input
              checked={enableIntegration}
              className="h-4 w-4 rounded border-input"
              disabled={isSaving}
              onChange={(e) => setEnableIntegration(e.target.checked)}
              type="checkbox"
            />
            Enable Integration
          </label>

          <DialogFooter>
            <Button
              disabled={isSaving}
              onClick={onCancel}
              type="button"
              variant="outline"
            >
              Cancel
            </Button>
            <Button disabled={isSaving} type="submit">
              {isSaving ? 'Creating...' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function AuthProviderEditDialog({
  isSaving,
  onCancel,
  onSave,
  provider,
}: EditDialogProps) {
  const [name, setName] = useState(provider.name)
  const [appType, setAppType] = useState<OAuthAppType>(
    provider.oauth_app_type ?? 'google',
  )
  const [clientId, setClientId] = useState(provider.client_id ?? '')
  const [issuerUrl, setIssuerUrl] = useState(provider.issuer_url ?? '')
  const [allowedDomains, setAllowedDomains] = useState<string[]>(
    provider.allowed_domains,
  )
  const [scopes, setScopes] = useState(provider.scopes.join(', '))
  const [domainDraft, setDomainDraft] = useState('')
  const [replaceSecret, setReplaceSecret] = useState(!provider.has_secret)
  const [secret, setSecret] = useState('')
  const [enableIntegration, setEnableIntegration] = useState(
    provider.usage === 'both',
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const showAllowedDomains = appType === 'google'
  const showIssuerUrl = appType === 'oidc'

  const addDomain = () => {
    const value = domainDraft.trim().toLowerCase()
    if (!value) return
    if (!allowedDomains.includes(value)) {
      setAllowedDomains([...allowedDomains, value])
    }
    setDomainDraft('')
  }

  const removeDomain = (value: string) => {
    setAllowedDomains(allowedDomains.filter((d) => d !== value))
  }

  const validate = (): boolean => {
    const next: Record<string, string> = {}
    if (!name.trim()) next.name = 'Name is required'
    if (!clientId.trim()) next.client_id = 'Client ID is required'
    if (replaceSecret && !secret && !provider.has_secret) {
      next.client_secret = 'Client secret is required'
    }
    if (showIssuerUrl) {
      if (!issuerUrl.trim()) {
        next.issuer_url = 'Issuer URL is required for OIDC'
      } else {
        try {
          const u = new URL(issuerUrl.trim())
          if (u.protocol !== 'https:') {
            next.issuer_url = 'Issuer URL must be https://'
          }
        } catch {
          next.issuer_url = 'Issuer URL must be a valid URL'
        }
      }
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    const payload: LoginProviderUpdate = {
      client_id: clientId.trim(),
      name: name.trim(),
      oauth_app_type: appType,
      usage: enableIntegration ? 'both' : 'login',
    }
    // Empty / unchanged secret preserves existing on the server.
    if (replaceSecret && secret) {
      payload.client_secret = secret
    } else {
      payload.client_secret = ''
    }
    if (showIssuerUrl && issuerUrl.trim()) {
      payload.issuer_url = issuerUrl.trim()
    }
    if (showAllowedDomains) {
      payload.allowed_domains = allowedDomains
    }
    if (scopes.trim()) {
      payload.scopes = scopes
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    } else {
      payload.scopes = []
    }
    onSave(payload)
  }

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
      open
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit {provider.name}</DialogTitle>
          <DialogDescription>
            {provider.organization_name && provider.third_party_service_name
              ? `${provider.organization_name} · ${provider.third_party_service_name}`
              : 'Login provider configuration.'}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              Display Name <span className="text-red-500">*</span>
            </label>
            <Input
              disabled={isSaving}
              onChange={(e) => setName(e.target.value)}
              value={name}
            />
            {errors.name && (
              <div className="mt-1 text-xs text-danger">{errors.name}</div>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              OAuth Type <span className="text-red-500">*</span>
            </label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
              disabled={isSaving}
              onChange={(e) => setAppType(e.target.value as OAuthAppType)}
              value={appType}
            >
              <option value="google">Google</option>
              <option value="github">GitHub</option>
              <option value="oidc">OpenID Connect</option>
            </select>
          </div>

          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              Client ID <span className="text-red-500">*</span>
            </label>
            <Input
              disabled={isSaving}
              onChange={(e) => setClientId(e.target.value)}
              value={clientId}
            />
            {errors.client_id && (
              <div className="mt-1 text-xs text-danger">{errors.client_id}</div>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              Client Secret
            </label>
            {provider.has_secret && !replaceSecret ? (
              <div
                className={
                  'flex items-center justify-between rounded-lg border border-input bg-secondary px-3 py-2'
                }
              >
                <span className="text-sm text-secondary">
                  Secret is set (hidden).
                </span>
                <Button
                  disabled={isSaving}
                  onClick={() => setReplaceSecret(true)}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Replace secret
                </Button>
              </div>
            ) : (
              <div className="space-y-1">
                <Input
                  autoComplete="new-password"
                  disabled={isSaving}
                  onChange={(e) => setSecret(e.target.value)}
                  placeholder={
                    provider.has_secret
                      ? 'Enter a new secret (leave blank to keep current)'
                      : ''
                  }
                  type="password"
                  value={secret}
                />
                {provider.has_secret && (
                  <Button
                    disabled={isSaving}
                    onClick={() => {
                      setReplaceSecret(false)
                      setSecret('')
                    }}
                    size="sm"
                    type="button"
                    variant="ghost"
                  >
                    Cancel replace
                  </Button>
                )}
                {errors.client_secret && (
                  <div className="text-xs text-danger">
                    {errors.client_secret}
                  </div>
                )}
              </div>
            )}
          </div>

          {showIssuerUrl && (
            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Issuer URL <span className="text-red-500">*</span>
              </label>
              <Input
                disabled={isSaving}
                onChange={(e) => setIssuerUrl(e.target.value)}
                placeholder="https://idp.example.com/"
                value={issuerUrl}
              />
              {errors.issuer_url && (
                <div className="mt-1 text-xs text-danger">
                  {errors.issuer_url}
                </div>
              )}
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              Scopes
            </label>
            <Input
              disabled={isSaving}
              onChange={(e) => setScopes(e.target.value)}
              placeholder="openid, email, profile (comma-separated)"
              value={scopes}
            />
          </div>

          {showAllowedDomains && (
            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Allowed Email Domains
              </label>
              <div
                className={
                  'flex flex-wrap items-center gap-2 rounded-lg border border-input bg-background p-2'
                }
              >
                {allowedDomains.map((d) => (
                  <span
                    className={
                      'inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary'
                    }
                    key={d}
                  >
                    {d}
                    <button
                      aria-label={`Remove ${d}`}
                      className="text-tertiary hover:text-primary"
                      disabled={isSaving}
                      onClick={() => removeDomain(d)}
                      onMouseDown={(e) => e.preventDefault()}
                      type="button"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                <input
                  className={
                    'min-w-[8rem] flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-muted-foreground'
                  }
                  disabled={isSaving}
                  onBlur={addDomain}
                  onChange={(e) => setDomainDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ',' || e.key === ' ') {
                      e.preventDefault()
                      addDomain()
                    } else if (
                      e.key === 'Backspace' &&
                      !domainDraft &&
                      allowedDomains.length > 0
                    ) {
                      setAllowedDomains(allowedDomains.slice(0, -1))
                    }
                  }}
                  placeholder={
                    allowedDomains.length === 0
                      ? 'example.com (Enter to add)'
                      : ''
                  }
                  value={domainDraft}
                />
              </div>
            </div>
          )}

          <label className="flex w-full items-center gap-2 text-sm text-secondary">
            <input
              checked={enableIntegration}
              className="h-4 w-4 rounded border-input"
              disabled={isSaving}
              onChange={(e) => setEnableIntegration(e.target.checked)}
              type="checkbox"
            />
            Enable Integration
          </label>

          <DialogFooter>
            <Button
              disabled={isSaving}
              onClick={onCancel}
              type="button"
              variant="outline"
            >
              Cancel
            </Button>
            <Button disabled={isSaving} type="submit">
              {isSaving ? 'Saving...' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

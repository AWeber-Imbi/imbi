import { useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle,
  KeyRound,
  Lock,
  Plus,
  Power,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  deleteLoginProvider,
  getLocalAuthConfig,
  listLoginProviders,
  listPluginPackages,
  setLoginProviderUsedAsLogin,
  updateLocalAuthConfig,
} from '@/api/endpoints'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EntityIcon } from '@/components/ui/entity-icon'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Sk, Swap } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useAuth } from '@/hooks/useAuth'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import { statusBadgeVariant } from '@/lib/status-colors'
import type { LocalAuthConfig } from '@/types'

import { AddAuthProviderDialog } from './AddAuthProviderDialog'

// fallow-ignore-next-line complexity
export function AuthProvidersManagement() {
  const queryClient = useQueryClient()
  const { user } = useAuth()

  const canManageLocalAuth =
    !!user?.is_admin ||
    (user?.permissions ?? []).includes('auth_providers:write')
  const canManageProviders =
    !!user?.is_admin || (user?.permissions ?? []).includes('integration:update')

  const localAuthQuery = useQuery({
    queryFn: ({ signal }) => getLocalAuthConfig(signal),
    queryKey: queryKeys.adminLocalAuth(),
  })

  const { data: plugins = [] } = useQuery({
    queryFn: ({ signal }) => listPluginPackages(signal),
    queryKey: queryKeys.pluginPackages(),
    staleTime: 60 * 1000,
  })

  // Login providers are global (org-less): authentication happens before any
  // organization context exists.
  const { data: providers, error: providersError } = useQuery({
    queryFn: ({ signal }) => listLoginProviders(signal),
    queryKey: queryKeys.loginProviders(),
  })

  // A plugin can back a login provider when it declares an `identity`
  // capability flagged `login_capable` in the manifest. Only enabled plugins
  // that don't already have a provider can back a new one — login providers
  // are one-per-plugin (name/slug derive from the plugin).
  const addablePlugins = useMemo(() => {
    // Until the providers query resolves we can't tell which plugins are
    // already configured, so expose none rather than offering an Add action
    // that could create a duplicate.
    if (!providers) return []
    const configured = new Set(providers.map((p) => p.plugin))
    return plugins.filter((p) => {
      if (!p.enabled || configured.has(p.slug)) return false
      const identity = p.capabilities.find((c) => c.kind === 'identity')
      return !!identity?.hints?.login_capable
    })
  }, [plugins, providers])

  // Plugin brand icons, keyed by slug, for the provider rows.
  const pluginIconBySlug = useMemo(() => {
    const map = new Map<string, string>()
    for (const p of plugins) if (p.icon) map.set(p.slug, p.icon)
    return map
  }, [plugins])

  const [addOpen, setAddOpen] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<null | {
    name: string
    slug: string
  }>(null)

  const localAuthMutation = useMutation({
    mutationFn: (enabled: boolean) => updateLocalAuthConfig({ enabled }),
    onError: (err) => {
      toast.error(
        `Failed to update local authentication: ${extractApiErrorDetail(err)}`,
      )
      queryClient.invalidateQueries({ queryKey: queryKeys.adminLocalAuth() })
    },
    onMutate: async (enabled: boolean) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.adminLocalAuth() })
      const previous = queryClient.getQueryData<LocalAuthConfig>(
        queryKeys.adminLocalAuth(),
      )
      if (previous) {
        queryClient.setQueryData<LocalAuthConfig>(queryKeys.adminLocalAuth(), {
          ...previous,
          enabled,
        })
      }
      return { previous }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.adminLocalAuth() })
      queryClient.invalidateQueries({
        queryKey: queryKeys.publicAuthProviders(),
      })
      toast.success('Local authentication updated')
    },
  })

  // Promote (or demote) a login provider as the instance-wide SSO provider.
  // The server enforces at most one active, so a full refetch reflects any
  // sibling that was demoted as a side effect.
  const loginProviderMutation = useMutation({
    mutationFn: ({
      slug,
      usedAsLogin,
    }: {
      slug: string
      usedAsLogin: boolean
    }) => setLoginProviderUsedAsLogin(slug, usedAsLogin),
    onError: (err) =>
      toast.error(
        `Failed to update login provider: ${extractApiErrorDetail(err)}`,
      ),
    onSuccess: (_data, { usedAsLogin }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.loginProviders() })
      queryClient.invalidateQueries({
        queryKey: queryKeys.publicAuthProviders(),
      })
      toast.success(
        usedAsLogin ? 'Login provider enabled' : 'Login provider disabled',
      )
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => deleteLoginProvider(slug),
    onError: (err) =>
      toast.error(
        `Failed to delete login provider: ${extractApiErrorDetail(err)}`,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.loginProviders() })
      queryClient.invalidateQueries({
        queryKey: queryKeys.publicAuthProviders(),
      })
      toast.success('Login provider deleted')
    },
  })

  return (
    <div className="max-w-4xl space-y-5">
      {!canManageLocalAuth && !canManageProviders && (
        <Alert icon={Power} variant="info">
          You don't have permission to modify authentication settings. Contact
          an administrator to make changes.
        </Alert>
      )}

      {/* Local authentication */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <div className="flex items-center gap-2">
            <Lock className="text-secondary size-5" />
            <CardTitle>Local Authentication</CardTitle>
          </div>
          <Swap
            ready={!!localAuthQuery.data}
            skeleton={<Sk circle h={20} w={20} />}
          >
            {localAuthQuery.data?.enabled ? (
              <CheckCircle className="text-status-review-dot size-5 shrink-0" />
            ) : (
              <AlertCircle className="text-tertiary size-5 shrink-0" />
            )}
          </Swap>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-tertiary text-xs">
            Allow users to sign in with an email address and password stored in
            Imbi.
          </p>
          <div className="border-input flex items-center justify-between rounded-lg border p-3">
            <div>
              <div className="text-primary text-sm">Enabled</div>
              <div className="text-tertiary text-xs">
                When disabled, the email/password form is hidden on the login
                page.
              </div>
            </div>
            <Swap
              ready={!!localAuthQuery.data}
              skeleton={<Sk h={20} r={9999} w={36} />}
            >
              <Switch
                checked={localAuthQuery.data?.enabled ?? false}
                disabled={!canManageLocalAuth || localAuthMutation.isPending}
                onCheckedChange={(checked) => localAuthMutation.mutate(checked)}
              />
            </Swap>
          </div>
        </CardContent>
      </Card>

      {/* SSO login provider (global) */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <div className="flex items-center gap-2">
            <KeyRound className="text-secondary size-5" />
            <CardTitle>SSO Login Provider</CardTitle>
          </div>
          {canManageProviders && addablePlugins.length > 0 && (
            <Button onClick={() => setAddOpen(true)} size="sm">
              <Plus className="size-4" />
              Add auth provider
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-tertiary text-xs">
            Choose which integration users sign in through. Only plugins that
            provide a login-capable identity are eligible, and at most one can
            be active. Login providers are global — sign-in happens before any
            organization is selected.
          </p>

          {providersError ? (
            <ErrorBanner
              error={providersError}
              title="Failed to load providers"
            />
          ) : (
            <Swap
              ready={!!providers}
              skeleton={
                <div className="space-y-2">
                  <Sk h={56} r={8} />
                  <Sk h={56} r={8} />
                </div>
              }
            >
              {(providers ?? []).length === 0 ? (
                <div className="border-input text-tertiary rounded-lg border border-dashed p-4 text-sm">
                  {addablePlugins.length > 0
                    ? `No login providers configured yet. Use “Add auth provider” to create one.`
                    : `No login-capable plugins are enabled. Enable one (e.g. Google, GitHub, OIDC) under Admin → Plugins first.`}
                </div>
              ) : (
                <div className="divide-tertiary border-tertiary divide-y rounded-lg border">
                  {(providers ?? []).map((provider) => (
                    <div
                      className="flex items-center justify-between gap-4 p-3"
                      key={provider.slug}
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        {pluginIconBySlug.get(provider.plugin) && (
                          <EntityIcon
                            className="text-tertiary size-4 shrink-0"
                            icon={pluginIconBySlug.get(provider.plugin)!}
                          />
                        )}
                        <span className="text-primary truncate text-sm font-medium">
                          {provider.name}
                        </span>
                        <Badge variant={statusBadgeVariant(provider.status)}>
                          {provider.status}
                        </Badge>
                      </div>
                      <div className="flex shrink-0 items-center gap-2.5">
                        <span className="text-tertiary text-xs">
                          {provider.used_as_login
                            ? 'Used for sign-in'
                            : 'Not used'}
                        </span>
                        <Switch
                          aria-label={`Use ${provider.name} for sign-in`}
                          checked={!!provider.used_as_login}
                          disabled={
                            !canManageProviders ||
                            loginProviderMutation.isPending ||
                            // Block promoting an inactive provider (it can't
                            // serve sign-in and would lock users out); still
                            // allow demoting one that's already in use.
                            (provider.status !== 'active' &&
                              !provider.used_as_login)
                          }
                          onCheckedChange={(checked) => {
                            if (checked && provider.status !== 'active') return
                            loginProviderMutation.mutate({
                              slug: provider.slug,
                              usedAsLogin: checked,
                            })
                          }}
                        />
                        {canManageProviders && (
                          <Button
                            aria-label={`Delete ${provider.name}`}
                            disabled={deleteMutation.isPending}
                            onClick={() =>
                              setPendingDelete({
                                name: provider.name,
                                slug: provider.slug,
                              })
                            }
                            size="icon"
                            variant="ghost"
                          >
                            <Trash2 className="text-danger size-4" />
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Swap>
          )}
        </CardContent>
      </Card>

      <AddAuthProviderDialog
        onClose={() => setAddOpen(false)}
        onCreated={() => {
          queryClient.invalidateQueries({
            queryKey: queryKeys.loginProviders(),
          })
          queryClient.invalidateQueries({
            queryKey: queryKeys.publicAuthProviders(),
          })
        }}
        open={addOpen}
        plugins={addablePlugins}
      />

      <ConfirmDialog
        confirmLabel="Delete"
        description={
          pendingDelete
            ? `Delete "${pendingDelete.name}"? This removes its credentials and stops it being available for sign-in. This cannot be undone.`
            : ''
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.slug)
          setPendingDelete(null)
        }}
        open={!!pendingDelete}
        title="Delete login provider"
      />
    </div>
  )
}

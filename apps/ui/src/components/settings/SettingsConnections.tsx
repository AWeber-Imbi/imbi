import { useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2, Loader2, RefreshCw, Unplug } from 'lucide-react'
import { toast } from 'sonner'

import {
  disconnectMyIdentity,
  getAdminPlugins,
  getMyIdentities,
  refreshMyIdentity,
  startMyIdentity,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { LoadingState } from '@/components/ui/loading-state'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { extractApiErrorDetail } from '@/lib/apiError'
import type {
  AdminPluginsResponse,
  IdentityConnectionResponse,
  IdentityConnectionStatus,
  InstalledPlugin,
} from '@/types'

interface ConnectionActionsProps {
  connection: IdentityConnectionResponse | null
  onConnect: () => void
  onDisconnect: () => void
  onRefresh: () => void
  pending: boolean
}

interface ConnectionRow {
  connection: IdentityConnectionResponse | null
  plugin: InstalledPlugin
}

const STATUS_LABEL: Record<'not_connected' | IdentityConnectionStatus, string> =
  {
    active: 'Connected',
    expired: 'Expired',
    not_connected: 'Not connected',
    revoked: 'Revoked',
  }

const STATUS_VARIANT: Record<
  'not_connected' | IdentityConnectionStatus,
  'default' | 'destructive' | 'outline' | 'secondary'
> = {
  active: 'default',
  expired: 'destructive',
  not_connected: 'outline',
  revoked: 'secondary',
}

export function SettingsConnections() {
  const queryClient = useQueryClient()
  // Pre-opened during the click handler so the popup-blocker accepts it as
  // a user-gesture window; the URL is assigned once the start mutation
  // resolves.  See the comment on `onConnect` below.
  const pendingAuthWindowRef = useRef<null | Window>(null)
  const [pendingDisconnectId, setPendingDisconnectId] = useState<null | string>(
    null,
  )

  const pluginsQuery = useQuery<AdminPluginsResponse>({
    queryFn: ({ signal }) => getAdminPlugins(signal),
    queryKey: ['admin-plugins'],
    staleTime: 60 * 1000,
  })

  const connectionsQuery = useQuery<IdentityConnectionResponse[]>({
    queryFn: ({ signal }) => getMyIdentities(signal),
    queryKey: ['me-identities'],
    staleTime: 30 * 1000,
  })

  const startMutation = useMutation({
    mutationFn: (pluginId: string) =>
      startMyIdentity(pluginId, {
        return_to: '/settings/connections',
      }),
    onError: (err) => {
      pendingAuthWindowRef.current?.close()
      pendingAuthWindowRef.current = null
      toast.error(
        extractApiErrorDetail(err) ?? 'Failed to start the connect flow',
      )
    },
    onSuccess: (data) => {
      // Device-flow plugins (AWS IAM IC) return a polling descriptor
      // alongside the URL.  Phase 1 just opens the URL in a new tab and
      // tells the user to complete the flow there; the polling
      // descriptor will be wired into a modal in a follow-up.
      if (data.polling) {
        toast.info(`Enter code ${data.polling.user_code} on the AWS page`)
      }
      const authWindow = pendingAuthWindowRef.current
      pendingAuthWindowRef.current = null
      if (authWindow) {
        authWindow.location.assign(data.authorization_url)
      } else {
        toast.error('Popup blocked. Please allow popups and try again.')
      }
    },
  })

  const refreshMutation = useMutation({
    mutationFn: (pluginId: string) => refreshMyIdentity(pluginId),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to refresh connection')
    },
    onSuccess: () => {
      toast.success('Connection refreshed')
      void queryClient.invalidateQueries({
        queryKey: ['me-identities'],
      })
    },
  })

  const disconnectMutation = useMutation({
    mutationFn: (pluginId: string) => disconnectMyIdentity(pluginId),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to disconnect')
    },
    onSuccess: () => {
      toast.success('Disconnected')
      setPendingDisconnectId(null)
      void queryClient.invalidateQueries({
        queryKey: ['me-identities'],
      })
    },
  })

  if (pluginsQuery.isLoading || connectionsQuery.isLoading) {
    return <LoadingState label="Loading connections..." />
  }

  if (pluginsQuery.isError) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-destructive">
          {extractApiErrorDetail(pluginsQuery.error) ??
            'Failed to load plugins'}
        </CardContent>
      </Card>
    )
  }

  if (connectionsQuery.isError) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-destructive">
          {extractApiErrorDetail(connectionsQuery.error) ??
            'Failed to load connections'}
        </CardContent>
      </Card>
    )
  }

  const identityPlugins = (pluginsQuery.data?.installed ?? []).filter(
    (p) => p.enabled && p.plugin_type === 'identity',
  )

  if (identityPlugins.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Link2 className="mx-auto mb-3 h-8 w-8 text-secondary" />
          <h2 className="mb-1 text-base font-medium text-primary">
            No identity providers
          </h2>
          <p className="text-sm text-secondary">
            Ask your administrator to enable an identity plugin (OIDC, GitHub,
            AWS IAM Identity Center) to connect your accounts.
          </p>
        </CardContent>
      </Card>
    )
  }

  // Phase 1: a Plugin row's id isn't surfaced on the admin/plugins
  // catalog (which is keyed on slug), so we join connections to plugins
  // by slug.  The host's start endpoint accepts either the node id or
  // the slug; the latter is unambiguous when only one Plugin exists per
  // slug, which matches the Phase-1 catalog.
  const connectionsByPluginSlug = new Map<string, IdentityConnectionResponse>()
  for (const c of connectionsQuery.data ?? []) {
    connectionsByPluginSlug.set(c.plugin_slug, c)
  }

  const rows: ConnectionRow[] = identityPlugins.map((plugin) => ({
    connection: connectionsByPluginSlug.get(plugin.slug) ?? null,
    plugin,
  }))

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-medium text-primary">
          Third-party connections
        </h2>
        <p className="mt-1 text-sm text-secondary">
          Connect your account to identity providers so Imbi can run AWS,
          GitHub, and OIDC operations as you instead of a shared service
          principal.
        </p>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Provider</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>Scopes</TableHead>
                <TableHead className="w-48 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ connection, plugin }) => {
                const status: 'not_connected' | IdentityConnectionStatus =
                  connection?.status ?? 'not_connected'
                return (
                  <TableRow key={plugin.slug}>
                    <TableCell>
                      <div className="font-medium">{plugin.name}</div>
                      {plugin.description && (
                        <div className="text-xs text-secondary">
                          {plugin.description}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[status]}>
                        {STATUS_LABEL[status]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-secondary">
                      {formatRelative(connection?.last_used_at ?? null)}
                    </TableCell>
                    <TableCell className="max-w-[260px] truncate text-xs text-secondary">
                      {connection?.scopes?.length
                        ? connection.scopes.join(', ')
                        : '—'}
                    </TableCell>
                    <TableCell className="text-right">
                      <ConnectionActions
                        connection={connection}
                        onConnect={() => {
                          // Open the auth tab synchronously inside the
                          // click handler so the browser treats it as a
                          // user-initiated popup; the URL is filled in
                          // once startMutation.onSuccess fires.
                          pendingAuthWindowRef.current = window.open(
                            '',
                            '_blank',
                            'noopener,noreferrer',
                          )
                          startMutation.mutate(plugin.slug)
                        }}
                        onDisconnect={() => setPendingDisconnectId(plugin.slug)}
                        onRefresh={() => refreshMutation.mutate(plugin.slug)}
                        pending={
                          startMutation.isPending ||
                          refreshMutation.isPending ||
                          disconnectMutation.isPending
                        }
                      />
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <ConfirmDialog
        confirmLabel="Disconnect"
        description="Disconnecting revokes the connection at the provider when possible and removes it from Imbi. You'll need to reconnect to use this provider again."
        onCancel={() => setPendingDisconnectId(null)}
        onConfirm={() => {
          if (pendingDisconnectId) {
            disconnectMutation.mutate(pendingDisconnectId)
          }
        }}
        open={pendingDisconnectId !== null}
        title="Disconnect provider?"
      />
    </div>
  )
}

function ConnectionActions({
  connection,
  onConnect,
  onDisconnect,
  onRefresh,
  pending,
}: ConnectionActionsProps) {
  if (!connection) {
    return (
      <Button
        disabled={pending}
        onClick={onConnect}
        size="sm"
        variant="outline"
      >
        {pending ? (
          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
        ) : (
          <Link2 className="mr-1 h-3 w-3" />
        )}
        Connect
      </Button>
    )
  }
  if (connection.status === 'active') {
    return (
      <div className="flex justify-end gap-2">
        <Button
          disabled={pending}
          onClick={onRefresh}
          size="sm"
          variant="ghost"
        >
          <RefreshCw className="mr-1 h-3 w-3" />
          Refresh
        </Button>
        <Button
          disabled={pending}
          onClick={onDisconnect}
          size="sm"
          variant="outline"
        >
          <Unplug className="mr-1 h-3 w-3" />
          Disconnect
        </Button>
      </div>
    )
  }
  return (
    <div className="flex justify-end gap-2">
      <Button
        disabled={pending}
        onClick={onConnect}
        size="sm"
        variant="outline"
      >
        Reconnect
      </Button>
      <Button
        disabled={pending}
        onClick={onDisconnect}
        size="sm"
        variant="ghost"
      >
        Forget
      </Button>
    </div>
  )
}

function formatRelative(value: null | string): string {
  if (!value) return '—'
  const ts = new Date(value)
  if (Number.isNaN(ts.getTime())) return '—'
  return ts.toLocaleString()
}

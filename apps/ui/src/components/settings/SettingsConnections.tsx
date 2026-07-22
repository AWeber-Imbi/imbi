import { useEffect, useRef, useState } from 'react'

import { useSearchParams } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2, Loader2, Plug, RefreshCw, Unplug } from 'lucide-react'
import { toast } from 'sonner'

import {
  disconnectMyIdentity,
  getMyIdentities,
  refreshMyIdentity,
  startMyIdentity,
} from '@/api/endpoints'
import { pluginIsIdentity } from '@/components/plugin-packages'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Sk } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useConnectableIdentities } from '@/hooks/useConnectableIdentities'
import { extractApiErrorDetail } from '@/lib/apiError'
import type {
  IdentityConnectionResponse,
  IdentityConnectionStatus,
  IdentityPollingDescriptor,
  PluginPackage,
} from '@/types'

import { DeviceCodePollingDialog } from './DeviceCodePollingDialog'

interface ConnectionActionsProps {
  connection: IdentityConnectionResponse | null
  // No connectable integration for this plugin (e.g. legacy integration
  // without a stable id) — the Connect action is unavailable.
  disabled?: boolean
  onConnect: () => void
  onDisconnect: () => void
  onRefresh: () => void
  pending: boolean
}

interface ConnectionRow {
  connection: IdentityConnectionResponse | null
  // The org integration backing this provider; null when the plugin has
  // no configured (identity-enabled) integration the actor can connect to.
  integrationId: null | string
  plugin: PluginPackage
}

interface DevicePoll {
  integrationId: string
  pluginLabel: string
  polling: IdentityPollingDescriptor
  state: string
}

// postMessage discriminator sent by an OAuth-callback popup to its
// opener so the parent can invalidate without timer-driven polling.
const IDENTITY_CONNECTED_MESSAGE = 'imbi:identity-connected'

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

// fallow-ignore-next-line complexity
export function SettingsConnections() {
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  // Pre-opened during the click handler so the popup-blocker accepts it as
  // a user-gesture window; the URL is assigned once the start mutation
  // resolves.  See the comment on `onConnect` below.
  const pendingAuthWindowRef = useRef<null | Window>(null)
  const [pendingDisconnectId, setPendingDisconnectId] = useState<null | string>(
    null,
  )
  const [devicePoll, setDevicePoll] = useState<DevicePoll | null>(null)
  // Tracks the prior value of ``devicePoll`` so the effect below can
  // tell a transition from "modal open" → "modal closed" apart from
  // the initial null → null on first mount.
  const prevDevicePollRef = useRef<DevicePoll | null>(null)
  // The verification popup the user authorizes in.  Tracked outside
  // of React state because passing a cross-origin Window through
  // props makes React Refresh / DevTools throw a SecurityError when
  // they try to read ``$$typeof`` on it.
  const verificationWindowRef = useRef<null | Window>(null)
  // Incremented when the popup closes.  Drives the device-code
  // modal's "tick now" effect via a primitive prop.
  const [pokeNonce, setPokeNonce] = useState(0)

  // When this component mounts inside an OAuth-callback popup
  // (window.opener set, same origin), signal the opener that a connect
  // flight just landed and self-close.  The opener invalidates its
  // connections query in the message-listener below.
  // fallow-ignore-next-line complexity
  useEffect(() => {
    const opener = window.opener as null | Window
    if (!opener || opener === window || opener.closed) return
    try {
      opener.postMessage(
        { type: IDENTITY_CONNECTED_MESSAGE },
        window.location.origin,
      )
    } catch {
      // Cross-origin opener (shouldn't happen for our callback path,
      // but fail closed rather than throwing on mount).
      return
    }
    window.close()
  }, [])

  // Watch the verification popup at 1 Hz; when it closes, bump
  // ``pokeNonce`` so the device-code modal fires an immediate /poll
  // tick, and clear the ref.  Keeping this in the parent avoids
  // having to pass the Window through React props.
  useEffect(() => {
    if (!devicePoll) return
    const id = setInterval(() => {
      const popup = verificationWindowRef.current
      if (popup && popup.closed) {
        verificationWindowRef.current = null
        setPokeNonce((n) => n + 1)
        clearInterval(id)
      }
    }, 1000)
    return () => clearInterval(id)
  }, [devicePoll])

  // Whenever the device-flow modal transitions from open to closed —
  // for any reason: success, dismiss, or expiry — refetch the
  // connections list.  Belt-and-suspenders next to the explicit
  // refetch in onComplete/onDismiss; if either of those misfires
  // (race with cancellation, stale closure, etc.) this still flips
  // the row to its current state.
  useEffect(() => {
    const prev = prevDevicePollRef.current
    prevDevicePollRef.current = devicePoll
    if (prev !== null && devicePoll === null) {
      void queryClient.refetchQueries({ queryKey: ['me-identities'] })
    }
  }, [devicePoll, queryClient])

  // Listener side: parent invalidates ``me-identities`` whenever a
  // popup self-closes via the postMessage above.  Combined with
  // ``staleTime: 0`` and React Query's default ``refetchOnWindowFocus``,
  // the table flips to "Connected" the instant the redirect-flow
  // callback lands without any timer-driven polling on this side.
  useEffect(() => {
    // fallow-ignore-next-line complexity
    function handler(event: MessageEvent) {
      if (event.origin !== window.location.origin) return
      const data = event.data as unknown
      if (
        data !== null &&
        typeof data === 'object' &&
        (data as { type?: unknown }).type === IDENTITY_CONNECTED_MESSAGE
      ) {
        void queryClient.invalidateQueries({ queryKey: ['me-identities'] })
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [queryClient])

  const { connectableSlugs, integrationsQuery, pluginsQuery } =
    useConnectableIdentities(orgSlug)

  const connectionsQuery = useQuery<IdentityConnectionResponse[]>({
    queryFn: ({ signal }) => getMyIdentities(signal),
    queryKey: ['me-identities'],
    // ``staleTime: 0`` means React Query's default
    // ``refetchOnWindowFocus`` always fires when the user clicks back
    // to this tab from an OAuth popup — covers redirect flows on top
    // of the explicit postMessage above.
    staleTime: 0,
  })

  const startMutation = useMutation({
    // Identity connections target an Integration by its id (the host's
    // start endpoint matches on Integration.id), not the plugin slug.
    mutationFn: (variables: { integrationId: string; pluginLabel: string }) =>
      startMyIdentity(variables.integrationId, {
        return_to: '/settings/connections',
      }).then((data) => ({ data, ...variables })),
    onError: (err) => {
      pendingAuthWindowRef.current?.close()
      pendingAuthWindowRef.current = null
      toast.error(
        extractApiErrorDetail(err) ?? 'Failed to start the connect flow',
      )
    },
    onSuccess: ({ data, integrationId, pluginLabel }) => {
      const popup = pendingAuthWindowRef.current
      pendingAuthWindowRef.current = null
      if (popup) {
        popup.location.assign(data.authorization_url)
      } else if (!data.polling) {
        // Device flows can recover via the modal's "Open" button; only
        // redirect flows are blocked outright when the popup fails.
        toast.error('Popup blocked. Please allow popups and try again.')
      }
      // Device-flow plugins (e.g. AWS IAM IC) return a polling descriptor
      // — open the modal so the user sees the user code and we tick the
      // poll endpoint until the IdP issues tokens.  Stash the popup in
      // a ref so the close-watcher can see it without piping a
      // cross-origin Window through React props.
      if (data.polling) {
        verificationWindowRef.current = popup
        setPokeNonce(0)
        setDevicePoll({
          integrationId,
          pluginLabel,
          polling: data.polling,
          state: data.state,
        })
      }
    },
  })

  const refreshMutation = useMutation({
    mutationFn: (integrationId: string) => refreshMyIdentity(integrationId),
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
    mutationFn: (integrationId: string) => disconnectMyIdentity(integrationId),
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

  // Honor ``?connect=<slug>`` from the dashboard's
  // UnconnectedIntegrationWidget — auto-kick off the connect flow on
  // mount, then strip the param so a refresh doesn't re-trigger it.
  const [searchParams, setSearchParams] = useSearchParams()
  const autoConnectSlug = searchParams.get('connect')
  const autoConnectFiredRef = useRef(false)
  // fallow-ignore-next-line complexity
  useEffect(() => {
    if (!autoConnectSlug || autoConnectFiredRef.current) return
    if (pluginsQuery.isLoading) return
    const plugin = (pluginsQuery.data ?? []).find(
      (p) => p.slug === autoConnectSlug && p.enabled,
    )
    autoConnectFiredRef.current = true
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete('connect')
        return next
      },
      { replace: true },
    )
    if (!plugin) return
    const integration = (integrationsQuery.data ?? []).find(
      (i) => i.plugin === plugin.slug && i.capabilities?.identity?.enabled,
    )
    if (!integration?.id) {
      toast.error(`No connectable ${plugin.name} integration is configured`)
      return
    }
    pendingAuthWindowRef.current = window.open('', '_blank')
    startMutation.mutate({
      integrationId: integration.id,
      pluginLabel: plugin.name,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    autoConnectSlug,
    pluginsQuery.isLoading,
    pluginsQuery.data,
    integrationsQuery.data,
  ])

  if (
    pluginsQuery.isLoading ||
    connectionsQuery.isLoading ||
    (!!orgSlug && integrationsQuery.isLoading)
  ) {
    return <ConnectionsSkeleton />
  }

  if (pluginsQuery.isError) {
    return (
      <Card>
        <CardContent className="text-destructive py-8 text-center text-sm">
          {extractApiErrorDetail(pluginsQuery.error) ??
            'Failed to load plugins'}
        </CardContent>
      </Card>
    )
  }

  if (connectionsQuery.isError) {
    return (
      <Card>
        <CardContent className="text-destructive py-8 text-center text-sm">
          {extractApiErrorDetail(connectionsQuery.error) ??
            'Failed to load connections'}
        </CardContent>
      </Card>
    )
  }

  // Only identity plugins that have a configured integration in this org
  // are connectable — global login providers (org-less) and merely
  // installed-but-unconfigured plugins are excluded (see
  // useConnectableIdentities).
  const identityPlugins = (pluginsQuery.data ?? []).filter(
    (p) => p.enabled && pluginIsIdentity(p) && connectableSlugs.has(p.slug),
  )

  if (identityPlugins.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Link2 className="text-secondary mx-auto mb-3 size-8" />
          <h2 className="text-primary mb-1 text-base font-medium">
            No identity providers
          </h2>
          <p className="text-secondary text-sm">
            Ask your administrator to enable an identity plugin (OIDC, GitHub,
            AWS IAM Identity Center) to connect your accounts.
          </p>
        </CardContent>
      </Card>
    )
  }

  // The identity-enabled integration backing each plugin, keyed by plugin
  // slug; the connect flow targets its id. Connections join to their
  // integration by id.
  const integrationByPluginSlug = new Map<string, string>()
  for (const i of integrationsQuery.data ?? []) {
    if (i.capabilities?.identity?.enabled && i.id) {
      integrationByPluginSlug.set(i.plugin, i.id)
    }
  }
  const connectionsByIntegrationId = new Map<
    string,
    IdentityConnectionResponse
  >()
  for (const c of connectionsQuery.data ?? []) {
    connectionsByIntegrationId.set(c.integration_id, c)
  }

  const rows: ConnectionRow[] = identityPlugins.map((plugin) => {
    const integrationId = integrationByPluginSlug.get(plugin.slug) ?? null
    return {
      connection: integrationId
        ? (connectionsByIntegrationId.get(integrationId) ?? null)
        : null,
      integrationId,
      plugin,
    }
  })

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-primary text-base font-medium">
          Third-party connections
        </h2>
        <p className="text-secondary mt-1 text-sm">
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
                <TableHead className="w-48 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {/* fallow-ignore-next-line complexity */}
              {rows.map(({ connection, integrationId, plugin }) => {
                const status: 'not_connected' | IdentityConnectionStatus =
                  connection?.status ?? 'not_connected'
                return (
                  <TableRow key={plugin.slug}>
                    <TableCell>
                      <ProviderCell plugin={plugin} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[status]}>
                        {STATUS_LABEL[status]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-secondary text-sm">
                      {formatRelative(connection?.last_used_at ?? null)}
                    </TableCell>
                    <TableCell className="text-right">
                      <ConnectionActions
                        connection={connection}
                        disabled={!integrationId}
                        onConnect={() => {
                          if (!integrationId) return
                          // Open the auth tab synchronously inside the
                          // click handler so the browser treats it as a
                          // user-initiated popup; the URL is filled in
                          // once startMutation.onSuccess fires.  We can't
                          // pass `noopener`/`noreferrer` here — both
                          // cause window.open to return null, which loses
                          // the reference we need to navigate the tab.
                          pendingAuthWindowRef.current = window.open(
                            '',
                            '_blank',
                          )
                          startMutation.mutate({
                            integrationId,
                            pluginLabel: plugin.name,
                          })
                        }}
                        onDisconnect={() =>
                          integrationId && setPendingDisconnectId(integrationId)
                        }
                        onRefresh={() =>
                          integrationId && refreshMutation.mutate(integrationId)
                        }
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

      <DeviceCodePollingDialog
        onComplete={() => {
          toast.success('Connection established')
          setDevicePoll(null)
          // ``refetchQueries`` always issues the network round-trip
          // and updates the cache regardless of observer state;
          // ``invalidateQueries`` only refetches active observers and
          // can no-op silently if the timing is unlucky.  Belt and
          // suspenders: also call .refetch() on the active query.
          void queryClient.refetchQueries({
            queryKey: ['me-identities'],
          })
          void connectionsQuery.refetch()
        }}
        onDismiss={() => {
          setDevicePoll(null)
          // Refetch on dismiss in case the IdP completed between the
          // last /poll tick and the user closing the modal.
          void queryClient.refetchQueries({
            queryKey: ['me-identities'],
          })
          void connectionsQuery.refetch()
        }}
        open={devicePoll !== null}
        pluginLabel={devicePoll?.pluginLabel ?? ''}
        pluginSlug={devicePoll?.integrationId ?? ''}
        pokeNonce={pokeNonce}
        polling={devicePoll?.polling ?? null}
        state={devicePoll?.state ?? ''}
      />
    </div>
  )
}

// fallow-ignore-next-line complexity
function ConnectionActions({
  connection,
  disabled,
  onConnect,
  onDisconnect,
  onRefresh,
  pending,
}: ConnectionActionsProps) {
  if (!connection) {
    return (
      <Button
        disabled={pending || disabled}
        onClick={onConnect}
        size="sm"
        variant="outline"
      >
        {pending ? (
          <Loader2 className="mr-1 size-3 animate-spin" />
        ) : (
          <Link2 className="mr-1 size-3" />
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
          <RefreshCw className="mr-1 size-3" />
          Refresh
        </Button>
        <Button
          disabled={pending}
          onClick={onDisconnect}
          size="sm"
          variant="outline"
        >
          <Unplug className="mr-1 size-3" />
          Disconnect
        </Button>
      </div>
    )
  }
  return (
    <div className="flex justify-end gap-2">
      <Button
        disabled={pending || disabled}
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

// Footprint skeleton mirroring the connections table (provider, status,
// last-used, actions) while the plugins + connections queries are in flight.
function ConnectionsSkeleton() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-primary text-base font-medium">
          Third-party connections
        </h2>
        <p className="text-secondary mt-1 text-sm">
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
                <TableHead className="w-48 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody aria-busy>
              {Array.from({ length: 3 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <Sk h={24} r={6} w={24} />
                      <Sk line w={120} />
                    </div>
                  </TableCell>
                  <TableCell>
                    <Sk h={20} r={4} w={84} />
                  </TableCell>
                  <TableCell>
                    <Sk line w={120} />
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <Sk h={28} r={6} w={96} />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

function formatRelative(value: null | string): string {
  if (!value) return '—'
  const ts = new Date(value)
  if (Number.isNaN(ts.getTime())) return '—'
  return ts.toLocaleString()
}

// v3 PluginPackage carries no brand glyph, so the provider cell falls back
// to the generic Plug icon (the v2 InstalledPlugin.icon had no v3 source).
function ProviderCell({ plugin }: { plugin: PluginPackage }) {
  return (
    <div className="flex items-center gap-3">
      {plugin.icon ? (
        <EntityIcon
          className="text-tertiary size-6 shrink-0"
          icon={plugin.icon}
        />
      ) : (
        <Plug className="text-tertiary size-6 shrink-0" />
      )}
      <div className="font-medium">{plugin.name}</div>
    </div>
  )
}

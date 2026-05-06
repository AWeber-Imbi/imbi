import { useEffect, useRef, useState } from 'react'

import { useSearchParams } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2, Loader2, Plug, RefreshCw, Unplug } from 'lucide-react'
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
import { getIcon, iconRegistry, useIconRegistryVersion } from '@/lib/icons'
import type { IconComponent } from '@/lib/icons'
import type {
  AdminPluginsResponse,
  IdentityConnectionResponse,
  IdentityConnectionStatus,
  IdentityPollingDescriptor,
  InstalledPlugin,
} from '@/types'

import { DeviceCodePollingDialog } from './DeviceCodePollingDialog'

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

interface DevicePoll {
  pluginLabel: string
  pluginSlug: string
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

export function SettingsConnections() {
  const queryClient = useQueryClient()
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

  const pluginsQuery = useQuery<AdminPluginsResponse>({
    queryFn: ({ signal }) => getAdminPlugins(signal),
    queryKey: ['admin-plugins'],
    staleTime: 60 * 1000,
  })

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
    mutationFn: (variables: { pluginLabel: string; pluginSlug: string }) =>
      startMyIdentity(variables.pluginSlug, {
        return_to: '/settings/connections',
      }).then((data) => ({ data, ...variables })),
    onError: (err) => {
      pendingAuthWindowRef.current?.close()
      pendingAuthWindowRef.current = null
      toast.error(
        extractApiErrorDetail(err) ?? 'Failed to start the connect flow',
      )
    },
    onSuccess: ({ data, pluginLabel, pluginSlug }) => {
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
          pluginLabel,
          pluginSlug,
          polling: data.polling,
          state: data.state,
        })
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

  // Honor ``?connect=<slug>`` from the dashboard's
  // UnconnectedIntegrationWidget — auto-kick off the connect flow on
  // mount, then strip the param so a refresh doesn't re-trigger it.
  const [searchParams, setSearchParams] = useSearchParams()
  const autoConnectSlug = searchParams.get('connect')
  const autoConnectFiredRef = useRef(false)
  useEffect(() => {
    if (!autoConnectSlug || autoConnectFiredRef.current) return
    if (pluginsQuery.isLoading) return
    const plugin = (pluginsQuery.data?.installed ?? []).find(
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
    pendingAuthWindowRef.current = window.open('', '_blank')
    startMutation.mutate({
      pluginLabel: plugin.name,
      pluginSlug: plugin.slug,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoConnectSlug, pluginsQuery.isLoading, pluginsQuery.data])

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
                      <ProviderCell plugin={plugin} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[status]}>
                        {STATUS_LABEL[status]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-secondary">
                      {formatRelative(connection?.last_used_at ?? null)}
                    </TableCell>
                    <TableCell className="text-right">
                      <ConnectionActions
                        connection={connection}
                        onConnect={() => {
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
                            pluginLabel: plugin.name,
                            pluginSlug: plugin.slug,
                          })
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
        pluginSlug={devicePoll?.pluginSlug ?? ''}
        pokeNonce={pokeNonce}
        polling={devicePoll?.polling ?? null}
        state={devicePoll?.state ?? ''}
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

function ProviderCell({ plugin }: { plugin: InstalledPlugin }) {
  const version = useIconRegistryVersion()
  const iconValue = plugin.icon ?? null

  // Lazy-load whichever icon set owns this value, so the brand glyph
  // resolves on first render even if the set wasn't pre-loaded.
  useEffect(() => {
    if (iconValue) {
      void iconRegistry.loadSetFor(iconValue)
    }
  }, [iconValue])

  // ``getIcon`` returns null while the owning set is still in-flight;
  // re-derive on every registry version bump so the icon swaps in
  // once the chunk lands.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ResolvedIcon: IconComponent | null = iconValue
    ? getIcon(iconValue, null)
    : null
  // Reference ``version`` so React treats this cell as dependent on
  // registry changes (cheap; no hook needed beyond useIconRegistryVersion).
  void version

  return (
    <div className="flex items-center gap-3">
      {ResolvedIcon ? (
        <ResolvedIcon className="h-6 w-6 flex-shrink-0 text-secondary" />
      ) : (
        <Plug className="h-6 w-6 flex-shrink-0 text-tertiary" />
      )}
      <div className="font-medium">{plugin.name}</div>
    </div>
  )
}

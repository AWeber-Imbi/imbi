import { useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Blocks } from 'lucide-react'
import { toast } from 'sonner'

import {
  listIntegrations,
  listPluginPackages,
  setPluginPackageEnabled,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Sk } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { IconTooltip } from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import { extractApiErrorDetail } from '@/lib/apiError'
import { capabilityMeta } from '@/lib/capabilities'
import { queryKeys } from '@/lib/queryKeys'
import type { PluginPackage } from '@/types'

// fallow-ignore-next-line complexity
export function PluginsManagement() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug

  const [toDisable, setToDisable] = useState<null | PluginPackage>(null)

  const {
    data: plugins = [],
    error,
    isError,
    isLoading,
  } = useQuery({
    queryFn: ({ signal }) => listPluginPackages(signal),
    queryKey: queryKeys.pluginPackages(),
    staleTime: 60 * 1000,
  })

  // Integration counts are per current organization (integrations are
  // org-scoped; plugins are installed system-wide).
  const { data: integrations = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listIntegrations(orgSlug!, signal),
    queryKey: orgSlug ? queryKeys.integrations(orgSlug) : ['integrations'],
  })

  const countByPlugin = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const i of integrations) {
      counts[i.plugin] = (counts[i.plugin] ?? 0) + 1
    }
    return counts
  }, [integrations])

  const setEnabled = useMutation({
    mutationFn: ({ enabled, slug }: { enabled: boolean; slug: string }) =>
      setPluginPackageEnabled(slug, enabled),
    onError: (err) =>
      toast.error(extractApiErrorDetail(err) ?? 'Failed to update plugin'),
    onSuccess: (_data, { enabled, slug }) => {
      toast.success(`${slug} ${enabled ? 'enabled' : 'disabled'}`)
      void queryClient.invalidateQueries({
        queryKey: queryKeys.pluginPackages(),
      })
      setToDisable(null)
    },
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-primary text-2xl font-semibold tracking-tight">
          Plugins
        </h1>
        <p className="text-secondary mt-1 text-sm">
          Installed plugin packages. Plugins are installed with the server
          deployment — there is no install or uninstall from here.
        </p>
      </div>

      {isError ? (
        <Card>
          <CardContent className="text-destructive py-8 text-center text-sm">
            {extractApiErrorDetail(error) ?? 'Failed to load plugins'}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Plugin</TableHead>
                  <TableHead>Capabilities</TableHead>
                  <TableHead>Integrations</TableHead>
                  <TableHead className="text-center">Status</TableHead>
                  <TableHead className="text-right">Enabled</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody aria-busy={isLoading || undefined}>
                {isLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={`sk-${i}`}>
                      <TableCell>
                        <Sk line w="55%" />
                      </TableCell>
                      <TableCell>
                        <Sk line w={80} />
                      </TableCell>
                      <TableCell>
                        <Sk line w={40} />
                      </TableCell>
                      <TableCell>
                        <Sk line w={60} />
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end">
                          <Sk h={20} r={9999} w={40} />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                ) : plugins.length === 0 ? (
                  <TableRow>
                    <TableCell
                      className="text-muted-foreground py-12 text-center"
                      colSpan={5}
                    >
                      No plugins are installed.
                    </TableCell>
                  </TableRow>
                ) : (
                  // fallow-ignore-next-line complexity
                  plugins.map((plugin) => {
                    const count = countByPlugin[plugin.slug] ?? 0
                    return (
                      <TableRow key={plugin.slug}>
                        <TableCell>
                          <div className="flex items-center gap-3">
                            {plugin.icon ? (
                              <EntityIcon
                                className="text-tertiary size-6 shrink-0"
                                icon={plugin.icon}
                              />
                            ) : (
                              <Blocks className="text-tertiary size-6 shrink-0" />
                            )}
                            <div>
                              <div className="text-primary font-semibold">
                                {plugin.name}
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-tertiary font-mono text-xs">
                                  {plugin.slug}
                                </span>
                                <span className="text-muted-foreground font-mono text-xs">
                                  {plugin.package_version}
                                </span>
                              </div>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-tertiary flex flex-wrap items-center gap-2">
                            {plugin.capabilities.length === 0 ? (
                              <span className="text-muted-foreground text-sm">
                                —
                              </span>
                            ) : (
                              plugin.capabilities.map((cap) => {
                                const meta = capabilityMeta(cap.kind)
                                if (!meta) return null
                                const Icon = meta.icon
                                return (
                                  <IconTooltip key={cap.kind} label={cap.label}>
                                    <span aria-label={cap.label}>
                                      <Icon className="size-4" />
                                    </span>
                                  </IconTooltip>
                                )
                              })
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          {count > 0 ? (
                            <button
                              className="text-amber-text-mid text-sm hover:underline"
                              onClick={() => navigate('/admin/integrations')}
                              type="button"
                            >
                              {count}
                            </button>
                          ) : (
                            <span className="text-muted-foreground text-sm">
                              None
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-center">
                          <Badge
                            variant={plugin.enabled ? 'success' : 'warning'}
                          >
                            {plugin.enabled ? 'enabled' : 'disabled'}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end">
                            <Switch
                              aria-label={`Toggle ${plugin.name}`}
                              checked={plugin.enabled}
                              disabled={setEnabled.isPending}
                              onCheckedChange={(next) => {
                                if (next) {
                                  setEnabled.mutate({
                                    enabled: true,
                                    slug: plugin.slug,
                                  })
                                } else {
                                  setToDisable(plugin)
                                }
                              }}
                            />
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        confirmLabel="Disable"
        description={
          toDisable
            ? `Disable ${toDisable.name}? ${
                countByPlugin[toDisable.slug] ?? 0
              } integration(s) in this organization will go inactive. Configuration is preserved and the plugin can be re-enabled at any time.`
            : ''
        }
        onCancel={() => {
          if (!setEnabled.isPending) setToDisable(null)
        }}
        onConfirm={() => {
          if (toDisable) {
            setEnabled.mutate({ enabled: false, slug: toDisable.slug })
          }
        }}
        open={toDisable !== null}
        title="Disable plugin"
      />
    </div>
  )
}

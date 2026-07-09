import { useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Blocks, Package, Plus } from 'lucide-react'
import { toast } from 'sonner'

import {
  deleteIntegration,
  listIntegrations,
  listPluginPackages,
} from '@/api/endpoints'
import { AdminTable, type AdminTableColumn } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { EntityIcon } from '@/components/ui/entity-icon'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { IconTooltip } from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import { extractApiErrorDetail } from '@/lib/apiError'
import { capabilityMeta, orderCapabilities } from '@/lib/capabilities'
import { queryKeys } from '@/lib/queryKeys'
import { statusBadgeVariant } from '@/lib/status-colors'
import { cn } from '@/lib/utils'
import type { Integration } from '@/types'

import { AdminSection } from '../AdminSection'
import { IntegrationDetail } from './IntegrationDetail'
import { IntegrationWizard } from './IntegrationWizard'

interface IntegrationsFirstRunProps {
  onNew: () => void
  quickStart: { name: string; slug: string }[]
}

// fallow-ignore-next-line complexity
export function IntegrationsManagement() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const queryClient = useQueryClient()
  const { detailPath, goToCreate, goToDetail, goToList, slug, viewMode } =
    useAdminNav()

  const [search, setSearch] = useState('')
  const [pluginFilter, setPluginFilter] = useState<string>('all')

  const {
    data: integrations = [],
    error,
    isLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listIntegrations(orgSlug!, signal),
    queryKey: orgSlug ? queryKeys.integrations(orgSlug) : ['integrations'],
  })

  // Enabled plugin packages back the first-run quick-start cards and the
  // "plugin unavailable" degraded state.
  const { data: plugins = [] } = useQuery({
    queryFn: ({ signal }) => listPluginPackages(signal),
    queryKey: queryKeys.pluginPackages(),
    staleTime: 60 * 1000,
  })

  const enabledPluginSlugs = useMemo(
    () => new Set(plugins.filter((p) => p.enabled).map((p) => p.slug)),
    [plugins],
  )

  const pluginIconBySlug = useMemo(() => {
    const map = new Map<string, string>()
    for (const p of plugins) if (p.icon) map.set(p.slug, p.icon)
    return map
  }, [plugins])

  const deleteMutation = useMutation({
    mutationFn: (integration: Integration) =>
      deleteIntegration(orgSlug!, integration.slug),
    onError: (err) => {
      toast.error(`Failed to delete integration: ${extractApiErrorDetail(err)}`)
    },
    onSuccess: () => {
      if (orgSlug) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.integrations(orgSlug),
        })
      }
    },
  })

  const selected = useMemo(
    () => integrations.find((i) => i.slug === slug) ?? null,
    [integrations, slug],
  )

  const pluginOptions = useMemo(
    () => Array.from(new Set(integrations.map((i) => i.plugin))).sort(),
    [integrations],
  )

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    // fallow-ignore-next-line complexity
    return integrations.filter((i) => {
      if (pluginFilter !== 'all' && i.plugin !== pluginFilter) return false
      if (!q) return true
      return (
        i.name.toLowerCase().includes(q) ||
        i.slug.toLowerCase().includes(q) ||
        i.plugin.toLowerCase().includes(q)
      )
    })
  }, [integrations, pluginFilter, search])

  if (viewMode === 'create') {
    return (
      <IntegrationWizard
        onCancel={goToList}
        onCreated={(created) => goToDetail(created.slug)}
        plugins={plugins.filter((p) => p.enabled)}
      />
    )
  }

  if (viewMode === 'detail' || viewMode === 'edit') {
    return (
      <IntegrationDetail
        onBack={goToList}
        // Seed from the list while the detail query loads.
        seed={selected}
        slug={slug ?? ''}
      />
    )
  }

  // First-run experience: no integrations at all.
  if (!isLoading && !error && integrations.length === 0) {
    return (
      <IntegrationsFirstRun
        onNew={goToCreate}
        quickStart={plugins.filter((p) => p.enabled).slice(0, 4)}
      />
    )
  }

  const columns: AdminTableColumn<Integration>[] = [
    {
      header: 'Name',
      key: 'name',
      render: (i) => {
        const unavailable = !enabledPluginSlugs.has(i.plugin)
        const icon = pluginIconBySlug.get(i.plugin)
        return (
          <div className="flex min-w-0 items-center gap-3">
            {icon ? (
              <EntityIcon
                className="text-tertiary size-5 shrink-0"
                icon={icon}
              />
            ) : (
              <Blocks className="text-tertiary size-5 shrink-0" />
            )}
            <span
              className={cn(
                'truncate font-semibold',
                unavailable ? 'text-tertiary' : 'text-primary',
              )}
            >
              {i.name}
            </span>
          </div>
        )
      },
    },
    {
      header: 'Capabilities',
      // Stack above the full-row link overlay so the icon tooltips get hover.
      interactive: true,
      key: 'capabilities',
      render: (i) => {
        const kinds = enabledCapabilities(i)
        if (kinds.length === 0) {
          return <span className="text-tertiary text-sm">—</span>
        }
        return (
          <div className="text-tertiary flex flex-wrap items-center gap-2.5">
            {kinds.map((kind) => {
              const meta = capabilityMeta(kind)
              if (!meta) return null
              const Icon = meta.icon
              return (
                <IconTooltip key={kind} label={meta.label}>
                  <span aria-label={meta.label}>
                    <Icon className="size-4" />
                  </span>
                </IconTooltip>
              )
            })}
          </div>
        )
      },
    },
    {
      cellAlign: 'center',
      header: 'Status',
      headerAlign: 'center',
      key: 'status',
      render: (i) =>
        enabledPluginSlugs.has(i.plugin) ? (
          <Badge variant={statusBadgeVariant(i.status)}>{i.status}</Badge>
        ) : (
          <Badge variant="warning">plugin unavailable</Badge>
        ),
    },
  ]

  return (
    <AdminSection
      createLabel="New integration"
      error={error}
      errorTitle="Failed to load integrations"
      headerExtras={
        pluginOptions.length > 1 ? (
          <Select onValueChange={setPluginFilter} value={pluginFilter}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder="All plugins" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All plugins</SelectItem>
              {pluginOptions.map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : undefined
      }
      onCreate={goToCreate}
      onSearchChange={setSearch}
      search={search}
      searchPlaceholder="Filter integrations…"
    >
      <AdminTable<Integration>
        columns={columns}
        emptyMessage={
          search || pluginFilter !== 'all'
            ? 'No integrations match your filter.'
            : 'No integrations yet.'
        }
        getDeleteLabel={(i) => i.name}
        getRowHref={(i) => detailPath(i.slug)}
        getRowKey={(i) => i.slug}
        isDeleting={deleteMutation.isPending}
        loading={isLoading}
        onDelete={(i) => deleteMutation.mutate(i)}
        rows={filtered}
      />
    </AdminSection>
  )
}

// Capability kinds that are enabled on an integration, in display order.
function enabledCapabilities(integration: Integration): string[] {
  return orderCapabilities(
    Object.entries(integration.capabilities)
      .filter(([, toggle]) => toggle.enabled)
      .map(([kind]) => kind),
  )
}

function IntegrationsFirstRun({
  onNew,
  quickStart,
}: IntegrationsFirstRunProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center px-10 py-14 text-center">
        <div className="bg-secondary text-tertiary mb-4 flex size-13 items-center justify-center rounded-xl">
          <Blocks className="size-6" />
        </div>
        <div className="text-primary text-lg font-semibold">
          No integrations yet
        </div>
        <div className="text-secondary mt-1.5 max-w-md text-sm">
          Connect GitHub, AWS, and other platforms to your projects. Pick a
          plugin, name the connection, and flip on what you want.
        </div>
        <Button
          className="bg-action text-action-foreground hover:bg-action-hover mt-5"
          onClick={onNew}
        >
          <Plus className="mr-2 size-4" />
          New integration
        </Button>
        {quickStart.length > 0 && (
          <>
            <div className="text-tertiary mt-9 mb-3 text-xs font-semibold tracking-wide uppercase">
              Quick start
            </div>
            <div className="grid w-full max-w-2xl grid-cols-2 gap-3 md:grid-cols-4">
              {quickStart.map((p) => (
                <button
                  className="border-secondary bg-primary hover:border-primary flex flex-col gap-1.5 rounded-lg border p-3.5 text-left transition-colors"
                  key={p.slug}
                  onClick={onNew}
                  type="button"
                >
                  <span className="text-primary inline-flex items-center gap-2 text-sm font-semibold">
                    <Package className="text-secondary size-4" />
                    {p.name}
                  </span>
                  <span className="text-tertiary font-mono text-xs">
                    {p.slug}
                  </span>
                </button>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

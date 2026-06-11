import { useMemo, useState } from 'react'

import { Link } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, CirclePlay, Package, PowerOff } from 'lucide-react'
import { toast } from 'sonner'

import { getAdminPlugins, setAdminPluginEnabled } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Sk } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import type { AdminPluginsResponse, InstalledPlugin } from '@/types'

type ActiveTab = 'disabled' | 'enabled'

interface DisabledListProps {
  parentLoading: boolean
  plugins: InstalledPlugin[]
}

interface EnabledListProps {
  error: unknown
  isError: boolean
  isLoading: boolean
  plugins: InstalledPlugin[]
}

export function PluginsManagement() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('enabled')

  const tabs: { id: ActiveTab; label: string }[] = [
    { id: 'enabled', label: 'Enabled' },
    { id: 'disabled', label: 'Disabled' },
  ]

  const { data, error, isError, isLoading } = useQuery<AdminPluginsResponse>({
    queryFn: ({ signal }) => getAdminPlugins(signal),
    queryKey: queryKeys.adminPlugins(),
    staleTime: 60 * 1000,
  })

  const enabled = useMemo(
    () => (data?.installed ?? []).filter((p) => p.enabled),
    [data],
  )
  const disabled = useMemo(
    () => (data?.installed ?? []).filter((p) => !p.enabled),
    [data],
  )

  return (
    <div className="space-y-6">
      <Tabs
        onValueChange={(v) => setActiveTab(v as ActiveTab)}
        value={activeTab}
      >
        <TabsList className="border-tertiary h-auto justify-start rounded-none border-b bg-transparent p-0">
          {tabs.map((tab) => (
            <TabsTrigger
              className="text-secondary hover:text-primary data-[state=active]:border-info data-[state=active]:text-info rounded-none border-b-2 border-transparent px-4 py-3 text-sm font-medium data-[state=active]:shadow-none"
              key={tab.id}
              value={tab.id}
            >
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {activeTab === 'enabled' && (
        <EnabledList
          error={error}
          isError={isError}
          isLoading={isLoading}
          plugins={enabled}
        />
      )}
      {activeTab === 'disabled' && (
        <DisabledList parentLoading={isLoading} plugins={disabled} />
      )}
    </div>
  )
}

function DisabledList({ parentLoading, plugins }: DisabledListProps) {
  const queryClient = useQueryClient()

  const enableMutation = useMutation({
    mutationFn: (slug: string) => setAdminPluginEnabled(slug, true),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to enable plugin')
    },
    onSuccess: (_, slug) => {
      toast.success(`${slug} enabled`)
      void queryClient.invalidateQueries({
        queryKey: queryKeys.adminPlugins(),
      })
    },
  })

  if (parentLoading) {
    return <PluginTableSkeleton cols={4} />
  }

  if (plugins.length === 0) {
    return (
      <PluginEmptyState
        description="Every installed plugin is currently enabled."
        title="All Plugins Enabled"
      />
    )
  }

  return (
    <Card>
      <CardHeader className="px-6 py-4">
        <CardTitle>Disabled Plugins</CardTitle>
        <CardDescription>
          Installed plugins that are not yet enabled. Enable a plugin to make it
          available for project type and service assignments.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Plugin</TableHead>
              <TableHead>Package</TableHead>
              <TableHead>Version</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {plugins.map((plugin) => (
              <TableRow key={plugin.slug}>
                <TableCell>
                  <div className="font-medium">{plugin.name}</div>
                  {plugin.description && (
                    <div className="text-secondary text-xs">
                      {plugin.description}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <code className="bg-secondary rounded px-1.5 py-0.5 text-xs">
                    {plugin.package_name}
                  </code>
                </TableCell>
                <TableCell className="text-secondary text-sm">
                  {plugin.package_version}
                </TableCell>
                <TableCell>
                  <Button
                    disabled={enableMutation.isPending}
                    onClick={() => enableMutation.mutate(plugin.slug)}
                    size="sm"
                    variant="outline"
                  >
                    <CirclePlay className="mr-1 size-3" />
                    Enable
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function EnabledList({ error, isError, isLoading, plugins }: EnabledListProps) {
  const queryClient = useQueryClient()
  const [pluginToDisable, setPluginToDisable] =
    useState<InstalledPlugin | null>(null)

  const disableMutation = useMutation({
    mutationFn: (slug: string) => setAdminPluginEnabled(slug, false),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to disable plugin')
    },
    onSuccess: (_, slug) => {
      toast.success(`${slug} disabled`)
      void queryClient.invalidateQueries({
        queryKey: queryKeys.adminPlugins(),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.adminPlugin(slug),
      })
      setPluginToDisable(null)
    },
  })

  if (isLoading) {
    return <PluginTableSkeleton cols={8} />
  }

  if (isError) {
    return (
      <Card>
        <CardContent className="text-destructive py-8 text-center text-sm">
          {extractApiErrorDetail(error) ?? 'Failed to load plugins'}
        </CardContent>
      </Card>
    )
  }

  if (plugins.length === 0) {
    return (
      <PluginEmptyState
        description="Enable a plugin from the Disabled tab to make it available for project type and service assignments."
        title="No Enabled Plugins"
      />
    )
  }

  return (
    <>
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Plugin</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Package</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Auth</TableHead>
                <TableHead>Tabs</TableHead>
                <TableHead className="w-28" />
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {plugins.map((plugin) => (
                <TableRow
                  className="hover:bg-secondary/40 relative cursor-pointer"
                  key={plugin.slug}
                >
                  <TableCell>
                    <Link
                      aria-label={`View ${plugin.name}`}
                      className="focus-visible:ring-ring absolute inset-0 rounded-sm focus-visible:ring-2 focus-visible:outline-none"
                      to={`/admin/plugins/${plugin.slug}`}
                    />
                    <div className="font-medium">{plugin.name}</div>
                    <div className="text-secondary text-xs">
                      {plugin.description}
                    </div>
                    {plugin.login_capable && (
                      <div className="mt-1">
                        <Badge variant="outline">Login provider</Badge>
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">
                      {plugin.plugin_type ?? plugin.supported_tabs[0] ?? '—'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <code className="bg-secondary rounded px-1.5 py-0.5 text-xs">
                      {plugin.package_name}
                    </code>
                  </TableCell>
                  <TableCell className="text-secondary text-sm">
                    {plugin.package_version}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{plugin.auth_type}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      {plugin.supported_tabs.map((tab) => (
                        <Badge key={tab} variant="secondary">
                          {tab}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="relative z-10">
                    <Button
                      disabled={disableMutation.isPending}
                      onClick={(e) => {
                        e.stopPropagation()
                        setPluginToDisable(plugin)
                      }}
                      size="sm"
                      variant="outline"
                    >
                      <PowerOff className="mr-1 size-3" />
                      Disable
                    </Button>
                  </TableCell>
                  <TableCell>
                    <ChevronRight className="text-tertiary size-4" />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <ConfirmDialog
        confirmLabel="Disable"
        description={
          pluginToDisable
            ? `Disable ${pluginToDisable.name}? It will no longer be available for new project type or service assignments. Existing configuration is preserved and the plugin can be re-enabled at any time.`
            : ''
        }
        onCancel={() => {
          if (!disableMutation.isPending) setPluginToDisable(null)
        }}
        onConfirm={() => {
          if (pluginToDisable) disableMutation.mutate(pluginToDisable.slug)
        }}
        open={pluginToDisable !== null}
        title="Disable plugin"
      />
    </>
  )
}

// Skeleton plugin table — mirrors the row footprint (label column wide, the
// rest narrow) so the list reads as present while the query is in flight.
// Shared empty-state card for both the enabled and disabled plugin lists.
function PluginEmptyState({
  description,
  title,
}: {
  description: string
  title: string
}) {
  return (
    <Card>
      <CardContent className="py-12 text-center">
        <Package className="text-secondary mx-auto mb-3 size-8" />
        <CardTitle className="mb-1">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardContent>
    </Card>
  )
}

function PluginTableSkeleton({
  cols,
  rows = 5,
}: {
  cols: number
  rows?: number
}) {
  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableBody aria-busy>
            {Array.from({ length: rows }).map((_, r) => (
              <TableRow key={r}>
                {Array.from({ length: cols }).map((_, c) => (
                  <TableCell key={c}>
                    <Sk line w={c === 0 ? '55%' : 72} />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

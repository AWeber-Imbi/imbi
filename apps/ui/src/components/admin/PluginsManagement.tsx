import { useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CirclePlay, Package } from 'lucide-react'
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
    queryKey: ['admin-plugins'],
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
      <div className="border-b border-tertiary">
        <div className="flex gap-0">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id
            return (
              <button
                className={`border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? 'border-info text-info'
                    : 'border-transparent text-secondary hover:text-primary'
                }`}
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                type="button"
              >
                {tab.label}
              </button>
            )
          })}
        </div>
      </div>

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
      void queryClient.invalidateQueries({ queryKey: ['admin-plugins'] })
    },
  })

  if (parentLoading) {
    return <LoadingState label="Loading..." />
  }

  if (plugins.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Package className="mx-auto mb-3 h-8 w-8 text-secondary" />
          <CardTitle className="mb-1">All Plugins Enabled</CardTitle>
          <CardDescription>
            Every installed plugin is currently enabled.
          </CardDescription>
        </CardContent>
      </Card>
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
                    <div className="text-xs text-secondary">
                      {plugin.description}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                    {plugin.package_name}
                  </code>
                </TableCell>
                <TableCell className="text-sm text-secondary">
                  {plugin.package_version}
                </TableCell>
                <TableCell>
                  <Button
                    disabled={enableMutation.isPending}
                    onClick={() => enableMutation.mutate(plugin.slug)}
                    size="sm"
                    variant="outline"
                  >
                    <CirclePlay className="mr-1 h-3 w-3" />
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
  if (isLoading) {
    return <LoadingState label="Loading..." />
  }

  if (isError) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-destructive">
          {extractApiErrorDetail(error) ?? 'Failed to load plugins'}
        </CardContent>
      </Card>
    )
  }

  if (plugins.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Package className="mx-auto mb-3 h-8 w-8 text-secondary" />
          <CardTitle className="mb-1">No Enabled Plugins</CardTitle>
          <CardDescription>
            Enable a plugin from the Disabled tab to make it available for
            project type and service assignments.
          </CardDescription>
        </CardContent>
      </Card>
    )
  }

  return (
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
            </TableRow>
          </TableHeader>
          <TableBody>
            {plugins.map((plugin) => (
              <TableRow key={plugin.slug}>
                <TableCell>
                  <div className="font-medium">{plugin.name}</div>
                  <div className="text-xs text-secondary">
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
                  <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                    {plugin.package_name}
                  </code>
                </TableCell>
                <TableCell className="text-sm text-secondary">
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
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

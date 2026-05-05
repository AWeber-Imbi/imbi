import { useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Download, Package, Power, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  getAdminPluginCatalog,
  getAdminPlugins,
  installPlugin,
  setAdminPluginEnabled,
  uninstallPlugin,
} from '@/api/endpoints'
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
  CatalogEntry,
  InstalledPlugin,
} from '@/types'

type ActiveTab = 'catalog' | 'installed'

interface CatalogListProps {
  disabled: InstalledPlugin[]
  parentLoading: boolean
}

interface InstalledListProps {
  enabled: InstalledPlugin[]
  error: unknown
  isError: boolean
  isLoading: boolean
}

export function PluginsManagement() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('installed')

  const tabs: { id: ActiveTab; label: string }[] = [
    { id: 'installed', label: 'Installed' },
    { id: 'catalog', label: 'Catalog' },
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

      {activeTab === 'installed' && (
        <InstalledList
          enabled={enabled}
          error={error}
          isError={isError}
          isLoading={isLoading}
        />
      )}
      {activeTab === 'catalog' && (
        <CatalogList disabled={disabled} parentLoading={isLoading} />
      )}
    </div>
  )
}

function CatalogList({ disabled, parentLoading }: CatalogListProps) {
  const queryClient = useQueryClient()
  const [confirmPkg, setConfirmPkg] = useState<null | string>(null)

  const { data: catalog, isLoading: catalogLoading } = useQuery({
    queryFn: ({ signal }) => getAdminPluginCatalog(signal),
    queryKey: ['admin-plugin-catalog'],
    staleTime: 5 * 60 * 1000,
  })

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

  const installMutation = useMutation({
    mutationFn: (packageName: string) =>
      installPlugin({ package: packageName }),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to install plugin')
    },
    onSuccess: (result, packageName) => {
      if (result.errors?.length) {
        toast.warning(
          `${packageName} installed with warnings: ${result.errors.join(', ')}`,
        )
      } else {
        toast.success(
          `${packageName} installed (${result.loaded} plugin(s) loaded)`,
        )
      }
      void queryClient.invalidateQueries({ queryKey: ['admin-plugins'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-plugin-catalog'] })
    },
  })

  const uninstallMutation = useMutation({
    mutationFn: (packageName: string) => uninstallPlugin(packageName),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to uninstall plugin')
    },
    onSuccess: (_, packageName) => {
      toast.success(`${packageName} uninstalled`)
      setConfirmPkg(null)
      void queryClient.invalidateQueries({ queryKey: ['admin-plugins'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-plugin-catalog'] })
    },
  })

  if (parentLoading || catalogLoading) {
    return <LoadingState label="Loading..." />
  }

  // Catalog rows that aren't yet installed in the Python env.
  const installedPackages = new Set(disabled.map((p) => p.package_name))
  const catalogOnly: CatalogEntry[] = (catalog ?? []).filter(
    (e) => !installedPackages.has(e.package),
  )

  if (disabled.length === 0 && catalogOnly.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Package className="mx-auto mb-3 h-8 w-8 text-secondary" />
          <CardTitle className="mb-1">Catalog Empty</CardTitle>
          <CardDescription>
            Every known plugin is already installed and enabled.
          </CardDescription>
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <Card>
        <CardHeader className="px-6 py-4">
          <CardTitle>Plugin Catalog</CardTitle>
          <CardDescription>
            Installed plugins start disabled — enable them here to make them
            assignable. Uninstalled catalog entries can be installed at runtime.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Plugin</TableHead>
                <TableHead>Package</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-32" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {disabled.map((plugin) => (
                <TableRow key={`installed-${plugin.slug}`}>
                  <TableCell>
                    <div className="font-medium">{plugin.name}</div>
                    <div className="text-xs text-secondary">
                      {plugin.description}
                    </div>
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
                    <Badge variant="secondary">Installed · Disabled</Badge>
                  </TableCell>
                  <TableCell>
                    <Button
                      disabled={enableMutation.isPending}
                      onClick={() => enableMutation.mutate(plugin.slug)}
                      size="sm"
                      variant="outline"
                    >
                      <Power className="mr-1 h-3 w-3" />
                      Enable
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {catalogOnly.map((entry) => (
                <TableRow key={`catalog-${entry.package}`}>
                  <TableCell>
                    <div className="font-medium">{entry.package}</div>
                    {entry.author && (
                      <div className="text-xs text-secondary">
                        by {entry.author}
                      </div>
                    )}
                    {entry.description && (
                      <div className="text-xs text-secondary">
                        {entry.description}
                        {entry.docs_url && (
                          <a
                            className="hover:text-info/80 ml-1 inline-flex items-center gap-0.5 text-info"
                            href={entry.docs_url}
                            rel="noopener noreferrer"
                            target="_blank"
                          >
                            <BookOpen className="h-3 w-3" />
                            Docs
                          </a>
                        )}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                      {entry.package}
                    </code>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {entry.version}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">Not Installed</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        disabled={installMutation.isPending}
                        onClick={() => installMutation.mutate(entry.package)}
                        size="sm"
                        variant="outline"
                      >
                        <Download className="mr-1 h-3 w-3" />
                        Install
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {disabled.length > 0 && (
        <Card>
          <CardHeader className="px-6 py-4">
            <CardTitle className="text-base">Uninstall</CardTitle>
            <CardDescription>
              Remove a Python package from the running environment. Disable
              first if assignments still depend on it.
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Package</TableHead>
                  <TableHead className="w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {disabled.map((plugin) => (
                  <TableRow key={`uninstall-${plugin.package_name}`}>
                    <TableCell>
                      <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                        {plugin.package_name}
                      </code>
                    </TableCell>
                    <TableCell>
                      <Button
                        aria-label={`Uninstall ${plugin.package_name}`}
                        onClick={() => setConfirmPkg(plugin.package_name)}
                        size="icon"
                        variant="ghost"
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        description={`Uninstall ${confirmPkg ?? ''}? Plugin assignments will become unavailable.`}
        onCancel={() => setConfirmPkg(null)}
        onConfirm={() => {
          if (confirmPkg) uninstallMutation.mutate(confirmPkg)
        }}
        open={confirmPkg !== null}
        title="Uninstall Plugin"
      />
    </>
  )
}

function InstalledList({
  enabled,
  error,
  isError,
  isLoading,
}: InstalledListProps) {
  const queryClient = useQueryClient()

  const disableMutation = useMutation({
    mutationFn: (slug: string) => setAdminPluginEnabled(slug, false),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to disable plugin')
    },
    onSuccess: (_, slug) => {
      toast.success(`${slug} disabled`)
      void queryClient.invalidateQueries({ queryKey: ['admin-plugins'] })
    },
  })

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

  if (enabled.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Package className="mx-auto mb-3 h-8 w-8 text-secondary" />
          <CardTitle className="mb-1">No Enabled Plugins</CardTitle>
          <CardDescription>
            Enable a plugin from the Catalog tab to make it available for
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
              <TableHead>Package</TableHead>
              <TableHead>Version</TableHead>
              <TableHead>Auth</TableHead>
              <TableHead>Tabs</TableHead>
              <TableHead className="w-20" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {enabled.map((plugin) => (
              <TableRow key={plugin.slug}>
                <TableCell>
                  <div className="font-medium">{plugin.name}</div>
                  <div className="text-xs text-secondary">
                    {plugin.description}
                  </div>
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
                <TableCell>
                  <Button
                    aria-label={`Disable ${plugin.name}`}
                    disabled={disableMutation.isPending}
                    onClick={() => disableMutation.mutate(plugin.slug)}
                    size="icon"
                    variant="ghost"
                  >
                    <Power className="h-3 w-3 text-destructive" />
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

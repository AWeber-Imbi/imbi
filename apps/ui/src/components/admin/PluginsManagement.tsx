import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  BookOpen,
  CheckCircle,
  Download,
  Package,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  getAdminPluginCatalog,
  getAdminPlugins,
  installPlugin,
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
import type { AdminPluginsResponse, InstalledPlugin } from '@/types'

interface InstalledListProps {
  error: unknown
  installed: InstalledPlugin[]
  isError: boolean
  isLoading: boolean
}

type PluginTab = 'catalog' | 'installed' | 'unavailable'

interface UnavailableListProps {
  error: unknown
  isError: boolean
  isLoading: boolean
  unavailable: string[]
}

export function PluginsManagement() {
  const [activeTab, setActiveTab] = useState<PluginTab>('installed')

  const tabs: { id: PluginTab; label: string }[] = [
    { id: 'installed', label: 'Installed' },
    { id: 'catalog', label: 'Catalog' },
    { id: 'unavailable', label: 'Unavailable' },
  ]

  const { data, error, isError, isLoading } = useQuery<AdminPluginsResponse>({
    queryFn: ({ signal }) => getAdminPlugins(signal),
    queryKey: ['admin-plugins'],
    staleTime: 60 * 1000,
  })

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
          error={error}
          installed={data?.installed ?? []}
          isError={isError}
          isLoading={isLoading}
        />
      )}
      {activeTab === 'catalog' && <CatalogList />}
      {activeTab === 'unavailable' && (
        <UnavailableList
          error={error}
          isError={isError}
          isLoading={isLoading}
          unavailable={data?.unavailable ?? []}
        />
      )}
    </div>
  )
}

function CatalogList() {
  const queryClient = useQueryClient()

  const { data, error, isError, isLoading } = useQuery({
    queryFn: ({ signal }) => getAdminPluginCatalog(signal),
    queryKey: ['admin-plugin-catalog'],
    staleTime: 5 * 60 * 1000,
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

  if (isLoading) {
    return <LoadingState label="Loading..." />
  }

  if (isError) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-destructive">
          {extractApiErrorDetail(error) ?? 'Failed to load plugin catalog'}
        </CardContent>
      </Card>
    )
  }

  const entries = data ?? []

  return (
    <Card>
      <CardHeader className="px-6 py-4">
        <CardTitle>Plugin Catalog</CardTitle>
        <CardDescription>
          Catalog updates ship with Imbi releases. For production persistence,
          add plugins to the image&apos;s pyproject.toml.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {entries.length === 0 ? (
          <div className="py-8 text-center text-sm text-secondary">
            No catalog entries
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Package</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-28" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry) => (
                <TableRow key={entry.package}>
                  <TableCell>
                    <div className="font-medium">{entry.package}</div>
                    {entry.author && (
                      <div className="text-xs text-secondary">
                        by {entry.author}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-secondary">
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
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {entry.version}
                  </TableCell>
                  <TableCell>
                    {entry.status === 'installed' ? (
                      <Badge
                        className="flex w-fit items-center gap-1"
                        variant="secondary"
                      >
                        <CheckCircle className="h-3 w-3" />
                        Installed
                      </Badge>
                    ) : entry.status === 'update_available' ? (
                      <Badge className="flex w-fit items-center gap-1 bg-amber-bg text-amber-text">
                        <Download className="h-3 w-3" />
                        Update Available
                      </Badge>
                    ) : (
                      <Badge variant="secondary">Not Installed</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {entry.status !== 'installed' && (
                      <Button
                        disabled={installMutation.isPending}
                        onClick={() => installMutation.mutate(entry.package)}
                        size="sm"
                        variant="outline"
                      >
                        <Download className="mr-1 h-3 w-3" />
                        {entry.status === 'update_available'
                          ? 'Update'
                          : 'Install'}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function InstalledList({
  error,
  installed,
  isError,
  isLoading,
}: InstalledListProps) {
  const queryClient = useQueryClient()
  const [confirmPkg, setConfirmPkg] = useState<null | string>(null)

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

  if (installed.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Package className="mx-auto mb-3 h-8 w-8 text-secondary" />
          <CardTitle className="mb-1">No Plugins Installed</CardTitle>
          <CardDescription>
            Install plugins from the Catalog tab to enable Configuration and
            Logs features.
          </CardDescription>
        </CardContent>
      </Card>
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
                <TableHead>Package</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Tabs</TableHead>
                <TableHead className="w-20" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {installed.map((plugin) => (
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
                      aria-label={`Uninstall ${plugin.name}`}
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

function UnavailableList({
  error,
  isError,
  isLoading,
  unavailable,
}: UnavailableListProps) {
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

  if (unavailable.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <CheckCircle className="mx-auto mb-3 h-8 w-8 text-secondary" />
          <CardTitle className="mb-1">All Plugins Available</CardTitle>
          <CardDescription>
            All configured plugin nodes have a matching installed handler.
          </CardDescription>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="px-6 py-4">
        <CardTitle className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-destructive" />
          Unavailable Plugins
        </CardTitle>
        <CardDescription>
          These plugin slugs are referenced by Plugin nodes in the graph but
          have no installed handler. Install the package from the Catalog tab or
          update the image.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Slug</TableHead>
              <TableHead>Resolution</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {unavailable.map((slug) => (
              <TableRow key={slug}>
                <TableCell>
                  <code className="rounded bg-secondary px-1.5 py-0.5 text-sm">
                    {slug}
                  </code>
                </TableCell>
                <TableCell className="text-sm text-secondary">
                  Install from the Catalog tab or add to the image&apos;s
                  pyproject.toml
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

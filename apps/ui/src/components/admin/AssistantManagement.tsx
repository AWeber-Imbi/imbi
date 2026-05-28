import { useMemo, useState } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound, ScrollText, Server, ShieldCheck, Unlock } from 'lucide-react'

import {
  createMcpServer,
  deleteMcpServer,
  listMcpServers,
  updateMcpServer,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import type { MCPServer, MCPServerUpdate } from '@/types'

import { AdminSection } from './AdminSection'
import {
  McpServerForm,
  type McpServerSaveData,
} from './mcp-servers/McpServerForm'
import { McpServerStatusPill } from './mcp-servers/McpServerStatusPill'

type Filter = 'all' | 'disabled' | 'enabled' | 'issues'

const MCP_SERVERS_KEY = ['mcp-servers']

export function AssistantManagement() {
  const { goToCreate, goToEdit, goToList, slug, viewMode } = useAdminNav()
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: servers,
    updateMutation,
  } = useAdminCrud<
    MCPServer,
    Parameters<typeof createMcpServer>[0],
    { data: MCPServerUpdate; id: string },
    string
  >({
    createFn: createMcpServer,
    deleteErrorLabel: 'MCP server',
    deleteFn: deleteMcpServer,
    listFn: listMcpServers,
    onMutationSuccess: goToList,
    queryKey: MCP_SERVERS_KEY,
    updateFn: ({ data, id }) => updateMcpServer(id, data),
  })

  // Inline enable/disable from the list, without leaving the list view.
  const toggleMutation = useMutation({
    mutationFn: ({ enabled, id }: { enabled: boolean; id: string }) =>
      updateMcpServer(id, { enabled }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: MCP_SERVERS_KEY }),
  })

  const selectedServer = useMemo(
    () => servers.find((srv) => srv.slug === slug) ?? null,
    [servers, slug],
  )

  const filtered = servers.filter(
    (srv) => matchesFilter(srv, filter) && matchesQuery(srv, searchQuery),
  )

  const handleSave = (payload: McpServerSaveData) => {
    if (payload.mode === 'create') {
      createMutation.mutate(payload.data)
    } else {
      updateMutation.mutate({ data: payload.data, id: payload.id })
    }
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <McpServerForm
        error={createMutation.error ?? updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={goToList}
        onSave={handleSave}
        server={viewMode === 'edit' ? selectedServer : null}
      />
    )
  }

  const filterChips: { count: number; key: Filter; label: string }[] = [
    { count: servers.length, key: 'all', label: 'All' },
    {
      count: servers.filter((srv) => srv.enabled).length,
      key: 'enabled',
      label: 'Enabled',
    },
    {
      count: servers.filter((srv) => !srv.enabled).length,
      key: 'disabled',
      label: 'Disabled',
    },
    {
      count: servers.filter((srv) => matchesFilter(srv, 'issues')).length,
      key: 'issues',
      label: 'With issues',
    },
  ]

  return (
    <div className="space-y-6">
      <Tabs value="mcp">
        <TabsList>
          <TabsTrigger value="mcp">
            <Server className="mr-2 size-4" />
            MCP Servers
            <Badge className="ml-2" variant="neutral">
              {servers.length}
            </Badge>
          </TabsTrigger>
          <TabsTrigger disabled value="prompts">
            <ScrollText className="mr-2 size-4" />
            System Prompts
            <Badge className="ml-2" variant="neutral">
              Soon
            </Badge>
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {servers.length === 0 && !isLoading && !error ? (
        <McpEmptyState onCreate={goToCreate} />
      ) : (
        <AdminSection
          createLabel="Add MCP Server"
          error={error}
          errorTitle="Failed to load MCP servers"
          headerExtras={
            <SegmentedControl
              ariaLabel="Filter servers"
              onValueChange={(v) => setFilter(v as Filter)}
              value={filter}
            >
              {filterChips.map((chip) => (
                <SegmentedControlItem key={chip.key} value={chip.key}>
                  {chip.label}
                  <span className="text-tertiary ml-1 tabular-nums">
                    {chip.count}
                  </span>
                </SegmentedControlItem>
              ))}
            </SegmentedControl>
          }
          isLoading={isLoading}
          loadingLabel="Loading MCP servers..."
          onCreate={goToCreate}
          onSearchChange={setSearchQuery}
          search={searchQuery}
          searchPlaceholder="Search servers by name, slug, or URL..."
        >
          <AdminTable
            columns={[
              {
                header: 'Server',
                key: 'server',
                render: (srv) => (
                  <div className="flex items-center gap-3">
                    <div className="bg-secondary text-secondary flex size-9 shrink-0 items-center justify-center rounded-lg font-mono text-xs font-semibold">
                      {monogram(srv.name)}
                    </div>
                    <div className="min-w-0">
                      <div className="text-primary flex items-center gap-2 font-medium">
                        {srv.name}
                        <span className="text-tertiary font-mono text-xs">
                          /{srv.slug}
                        </span>
                      </div>
                      {srv.description && (
                        <div className="text-tertiary max-w-sm truncate text-sm">
                          {srv.description}
                        </div>
                      )}
                    </div>
                  </div>
                ),
              },
              {
                header: 'Endpoint',
                key: 'endpoint',
                render: (srv) => (
                  <span
                    className="text-secondary block max-w-[16rem] truncate font-mono text-xs"
                    title={srv.url}
                  >
                    {srv.url.replace(/^https?:\/\//, '')}
                  </span>
                ),
              },
              {
                header: 'Auth',
                key: 'auth',
                render: (srv) => {
                  const { Icon, text } = authSummary(srv)
                  return (
                    <span className="text-secondary inline-flex items-center gap-1.5 text-sm">
                      <Icon className="text-tertiary size-3.5" />
                      {text}
                    </span>
                  )
                },
              },
              {
                cellAlign: 'right',
                header: 'Tools',
                headerAlign: 'right',
                key: 'tools',
                render: (srv) => (
                  <span className="text-secondary font-mono text-sm tabular-nums">
                    {srv.tools_discovered ?? '—'}
                    {srv.ignored_tools.length > 0 && (
                      <span className="text-tertiary">
                        {' · '}
                        {srv.ignored_tools.length} hidden
                      </span>
                    )}
                  </span>
                ),
              },
              {
                header: 'Status',
                key: 'status',
                render: (srv) => <McpServerStatusPill server={srv} />,
              },
              {
                header: 'Enabled',
                key: 'enabled',
                render: (srv) => (
                  <span
                    className="inline-flex"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <Switch
                      aria-label={`${srv.enabled ? 'Disable' : 'Enable'} ${srv.name}`}
                      checked={srv.enabled}
                      disabled={toggleMutation.isPending}
                      onCheckedChange={(enabled) =>
                        toggleMutation.mutate({ enabled, id: srv.id })
                      }
                    />
                  </span>
                ),
              },
            ]}
            emptyMessage={
              searchQuery || filter !== 'all'
                ? 'No servers match your filters.'
                : 'No MCP servers configured yet.'
            }
            getDeleteLabel={(srv) => srv.name}
            getRowKey={(srv) => srv.slug}
            isDeleting={deleteMutation.isPending}
            onDelete={(srv) => deleteMutation.mutate(srv.id)}
            onRowClick={(srv) => goToEdit(srv.slug)}
            rows={filtered}
          />
          <div className="text-tertiary flex items-center justify-between text-xs">
            <span>
              Showing {filtered.length} of {servers.length} servers · tools
              surface as{' '}
              <code className="bg-secondary rounded px-1 py-0.5 font-mono">
                mcp_&#123;prefix&#125;_&#123;tool&#125;
              </code>
            </span>
          </div>
        </AdminSection>
      )}
    </div>
  )
}

function authSummary(server: MCPServer): {
  Icon: typeof KeyRound
  text: string
} {
  switch (server.auth_type) {
    case 'oauth_client_credentials':
      return { Icon: ShieldCheck, text: 'OAuth · client creds' }
    case 'static':
      return {
        Icon: KeyRound,
        text: `Static · ${server.static_header ?? 'header'}`,
      }
    default:
      return { Icon: Unlock, text: 'No auth' }
  }
}

function matchesFilter(server: MCPServer, filter: Filter): boolean {
  if (filter === 'enabled') return server.enabled
  if (filter === 'disabled') return !server.enabled
  if (filter === 'issues') {
    return server.status === 'degraded' || server.status === 'unreachable'
  }
  return true
}

function matchesQuery(server: MCPServer, query: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  return (
    server.name.toLowerCase().includes(q) ||
    server.slug.toLowerCase().includes(q) ||
    server.url.toLowerCase().includes(q) ||
    (server.description?.toLowerCase().includes(q) ?? false)
  )
}

function McpEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center py-16 text-center">
        <div className="bg-secondary text-tertiary mb-4 flex size-12 items-center justify-center rounded-xl">
          <Server className="size-6" />
        </div>
        <div className="text-primary text-base font-medium">
          No MCP servers configured
        </div>
        <p className="text-secondary mt-1.5 max-w-md text-sm">
          Connect a Model Context Protocol server to give the assistant access
          to external tools — GitHub, SonarQube, code search, anything that
          speaks streamable-HTTP MCP.
        </p>
        <button
          className="bg-action text-action-foreground hover:bg-action-hover mt-5 inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium"
          onClick={onCreate}
          type="button"
        >
          Add your first server
        </button>
      </CardContent>
    </Card>
  )
}

function monogram(name: string): string {
  return (name.trim() || '?').slice(0, 2).toUpperCase()
}

import { type ReactNode, useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot } from 'lucide-react'
import { toast } from 'sonner'

import { patchAgent } from '@/api/endpoints'
import { AdminSection } from '@/components/admin/AdminSection'
import { AdminTable } from '@/components/ui/admin-table'
import { FilterPopover } from '@/components/ui/filter-popover'
import { Switch } from '@/components/ui/switch'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { useIcon } from '@/lib/icons'
import { queryKeys } from '@/lib/queryKeys'
import type { Agent } from '@/types'

import { AgentLabels } from './AgentLabelChip'
import { agentsPath } from './agentsNav'

interface AgentListProps {
  agents: Agent[]
  error: unknown
  loading: boolean
  orgSlug: string
}

type FacetKey = 'label' | 'status' | 'team'

export function AgentList({ agents, error, loading, orgSlug }: AgentListProps) {
  const navigate = useNavigate()
  const canCreate = useHasPermission('agent:create')
  const canWrite = useHasPermission('agent:write')
  const [search, setSearch] = useState('')
  const [facets, setFacets] = useState<Record<FacetKey, string[]>>({
    label: [],
    status: [],
    team: [],
  })
  const toggleEnabled = useToggleEnabled(orgSlug)

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    const has = (key: FacetKey, value: string) =>
      facets[key].length === 0 || facets[key].includes(value)
    return agents.filter(
      (a) =>
        (!q ||
          [a.name, a.description ?? '', a.team?.name ?? '']
            .concat(a.tags.map((t) => t.name))
            .join(' ')
            .toLowerCase()
            .includes(q)) &&
        has('team', a.team?.slug ?? '') &&
        (facets.label.length === 0 ||
          a.tags.some((t) => facets.label.includes(t.slug))) &&
        has('status', a.enabled ? 'enabled' : 'disabled'),
    )
  }, [agents, facets, search])

  const facet = (
    key: FacetKey,
    label: string,
    options: { label: string; slug: string }[],
  ) => (
    <FilterPopover
      activeFilters={new Set(facets[key])}
      label={label}
      onClear={() => setFacets({ ...facets, [key]: [] })}
      onToggle={(slug) =>
        setFacets({
          ...facets,
          [key]: facets[key].includes(slug)
            ? facets[key].filter((s) => s !== slug)
            : [...facets[key], slug],
        })
      }
      options={options.map((o) => ({
        ...o,
        count: agents.filter((a) => facetValues(a, key).includes(o.slug))
          .length,
      }))}
    />
  )

  const teams = uniqueBySlug(agents.flatMap((a) => (a.team ? [a.team] : [])))
  const labels = uniqueBySlug(agents.flatMap((a) => a.tags))

  return (
    <AdminSection
      createLabel="New Agent"
      error={error}
      errorTitle="Failed to load agents"
      onCreate={
        canCreate ? () => navigate(agentsPath('manage', 'new')) : undefined
      }
      onSearchChange={setSearch}
      search={search}
      searchPlaceholder="Search agents, teams, labels…"
    >
      <AdminTable
        columns={[
          {
            header: 'Name',
            key: 'name',
            render: (a) => <AgentNameCell agent={a} />,
          },
          {
            header: header(
              'Owner team',
              facet(
                'team',
                'Owner team',
                teams.map((t) => ({ label: t.name, slug: t.slug })),
              ),
            ),
            key: 'team',
            render: (a) => (
              <span className="text-secondary text-sm">
                {a.team?.name ?? '—'}
              </span>
            ),
          },
          {
            header: header(
              'Labels',
              facet(
                'label',
                'Labels',
                labels.map((t) => ({ label: t.name, slug: t.slug })),
              ),
            ),
            key: 'labels',
            render: (a) => <AgentLabels tags={a.tags} />,
          },
          {
            header: header(
              'Status',
              facet('status', 'Status', [
                { label: 'Enabled', slug: 'enabled' },
                { label: 'Disabled', slug: 'disabled' },
              ]),
            ),
            interactive: true,
            key: 'status',
            render: (a) => (
              <div
                className="flex items-center gap-2"
                onClick={(e) => e.stopPropagation()}
              >
                {canWrite && (
                  <Switch
                    aria-label={`${a.enabled ? 'Disable' : 'Enable'} ${a.name}`}
                    checked={a.enabled}
                    disabled={toggleEnabled.isPending}
                    onCheckedChange={(enabled) =>
                      toggleEnabled.mutate({ enabled, slug: a.slug })
                    }
                  />
                )}
                <span
                  className={`text-xs whitespace-nowrap ${a.enabled ? 'text-secondary' : 'text-tertiary'}`}
                >
                  {a.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
            ),
          },
        ]}
        emptyMessage={
          agents.length === 0
            ? 'No agents yet.'
            : 'No agents match that search.'
        }
        getRowHref={(a) => agentsPath('manage', a.slug)}
        getRowKey={(a) => a.slug}
        getRowLabel={(a) => a.name}
        loading={loading}
        rows={rows}
      />
    </AdminSection>
  )
}

function AgentNameCell({ agent }: { agent: Agent }) {
  const Icon = useIcon(agent.icon, Bot)
  return (
    <div className="flex items-center gap-3">
      <Icon className="text-secondary size-4 shrink-0" />
      <div className="flex min-w-0 flex-col">
        <span className="text-sm font-medium whitespace-nowrap">
          {agent.name}
        </span>
        {agent.description && (
          <span className="text-tertiary max-w-65 truncate text-xs">
            {agent.description}
          </span>
        )}
      </div>
    </div>
  )
}

function facetValues(agent: Agent, key: FacetKey): string[] {
  if (key === 'team') return agent.team ? [agent.team.slug] : []
  if (key === 'label') return agent.tags.map((t) => t.slug)
  return [agent.enabled ? 'enabled' : 'disabled']
}

function header(text: string, control: ReactNode) {
  return (
    <span className="flex items-center gap-1">
      {text}
      {control}
    </span>
  )
}

function uniqueBySlug<T extends { name: string; slug: string }>(
  items: T[],
): T[] {
  const seen = new Map<string, T>()
  for (const item of items) if (!seen.has(item.slug)) seen.set(item.slug, item)
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name))
}

/** PATCH `enabled` with an optimistic list update; roll back on error. */
function useToggleEnabled(orgSlug: string) {
  const queryClient = useQueryClient()
  const key = queryKeys.agents(orgSlug)
  return useMutation({
    mutationFn: ({ enabled, slug }: { enabled: boolean; slug: string }) =>
      patchAgent(orgSlug, slug, [
        { op: 'replace', path: '/enabled', value: enabled },
      ]),
    onError: (error, _vars, previous) => {
      if (previous) queryClient.setQueryData(key, previous)
      toast.error(
        `Failed to change the agent status: ${extractApiErrorDetail(error)}`,
      )
    },
    onMutate: async ({ enabled, slug }) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<Agent[]>(key)
      queryClient.setQueryData<Agent[]>(key, (rows) =>
        rows?.map((a) => (a.slug === slug ? { ...a, enabled } : a)),
      )
      return previous
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: key }),
  })
}

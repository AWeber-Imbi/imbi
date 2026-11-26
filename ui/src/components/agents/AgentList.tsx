import { useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot } from 'lucide-react'
import { toast } from 'sonner'

import { patchAgent } from '@/api/endpoints'
import { AdminSection } from '@/components/admin/AdminSection'
import { TagChips } from '@/components/tags/TagChip'
import { AdminTable } from '@/components/ui/admin-table'
import { Switch } from '@/components/ui/switch'
import {
  headerWithFilter as header,
  useTableFacets,
  useTableSort,
} from '@/components/ui/table-controls'
import { UserIdentity } from '@/components/ui/user-identity'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useServiceAccountAgents } from '@/hooks/useServiceAccountAgents'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import { extractApiErrorDetail } from '@/lib/apiError'
import { useIcon } from '@/lib/icons'
import { queryKeys } from '@/lib/queryKeys'
import type { Agent } from '@/types'

import { formatMoney } from './agentDraft'
import { useAgentUsage } from './agentQueries'
import { agentsPath } from './agentsNav'
import { formatCount } from './agentUsage'

interface AgentListProps {
  agents: Agent[]
  error: unknown
  loading: boolean
  orgSlug: string
}

const FACET_KEYS = ['author', 'status', 'tag', 'team'] as const
type FacetKey = (typeof FACET_KEYS)[number]
type SortKey = 'author' | 'name' | 'tags' | 'team' | UsageKey
type Usage = { cost: number; runs: number }
// One accessor per usage column, shared by the cell and the sort.
const USAGE_METRICS = {
  avg: [(u: Usage) => (u.runs > 0 ? u.cost / u.runs : null), formatMoney],
  cost: [(u: Usage) => u.cost, formatMoney],
  runs: [(u: Usage) => u.runs, formatCount],
} as const
type UsageKey = keyof typeof USAGE_METRICS

export function AgentList({ agents, error, loading, orgSlug }: AgentListProps) {
  const navigate = useNavigate()
  const canCreate = useHasPermission('agent:create', orgSlug)
  const canWrite = useHasPermission('agent:write', orgSlug)
  const [search, setSearch] = useState('')
  const toggleEnabled = useToggleEnabled(orgSlug)
  const { data: usage } = useAgentUsage(orgSlug)
  const { displayNames } = useUserDisplayNames()
  const serviceAccounts = useServiceAccountAgents()
  const nameOf = (principal: string) =>
    serviceAccounts.get(principal)?.name ??
    displayNames.get(principal) ??
    principal
  const authorName = (a: Agent) => (a.created_by ? nameOf(a.created_by) : '')
  const usageOf = (a: Agent) => {
    if (!usage) return null
    const row = usage.agents.find((u) => u.agent_id === a.id)
    return { cost: Number(row?.cost ?? 0), runs: row?.tasks ?? 0 }
  }
  const sortValue = (a: Agent, key: SortKey): number | string => {
    if (key === 'name') return a.name
    if (key === 'author') return authorName(a)
    if (key === 'team') return a.team?.name ?? ''
    if (key === 'tags')
      return a.tags
        .map((t) => t.name)
        .sort()
        .join(' ')
    const u = usageOf(a)
    return (u && USAGE_METRICS[key][0](u)) ?? 0
  }
  const { sortButton, sorted } = useTableSort(sortValue)
  const { facet, matches } = useTableFacets(FACET_KEYS, facetValues, agents)
  const usageColumn = (key: UsageKey, header: string) => ({
    cellAlign: 'right' as const,
    header: sortButton(key, header),
    headerAlign: 'right' as const,
    key,
    render: (a: Agent) => {
      const u = usageOf(a)
      const [metric, format] = USAGE_METRICS[key]
      const v = u && metric(u)
      return (
        <span className="text-secondary font-mono text-sm tabular-nums">
          {v == null ? '—' : format(v)}
        </span>
      )
    },
  })

  const q = search.trim().toLowerCase()
  const rows = agents.filter(
    (a) =>
      (!q ||
        [a.name, a.description ?? '', a.team?.name ?? '', authorName(a)]
          .concat(a.tags.map((t) => t.name))
          .join(' ')
          .toLowerCase()
          .includes(q)) &&
      matches(a),
  )

  const teamNames = Object.fromEntries(
    agents.flatMap((a) => (a.team ? [[a.team.slug, a.team.name]] : [])),
  )
  const tagNames = Object.fromEntries(
    agents.flatMap((a) => a.tags.map((t) => [t.slug, t.name])),
  )

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
      searchPlaceholder="Search agents, teams, authors, tags…"
    >
      <AdminTable
        columns={[
          {
            header: sortButton('name', 'Name'),
            key: 'name',
            render: (a) => <AgentNameCell agent={a} />,
          },
          {
            header: header(
              sortButton('team', 'Owner team'),
              facet('team', 'Owner team', (s) => teamNames[s]),
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
              sortButton('author', 'Author'),
              facet('author', 'Author', nameOf),
            ),
            // The profile link stacks above the row link.
            interactive: true,
            key: 'author',
            render: (a) =>
              a.created_by ? (
                <UserIdentity
                  displayNames={displayNames}
                  email={a.created_by}
                  size="small"
                />
              ) : (
                <span className="text-tertiary text-sm">—</span>
              ),
          },
          usageColumn('runs', 'Runs 30d'),
          usageColumn('cost', 'Cost 30d'),
          usageColumn('avg', 'Avg / run'),
          {
            header: header(
              sortButton('tags', 'Tags'),
              facet('tag', 'Tags', (s) => tagNames[s]),
            ),
            key: 'tags',
            render: (a) => <TagChips tags={a.tags} />,
          },
          {
            header: header(
              'Status',
              facet('status', 'Status', (s) =>
                s === 'enabled' ? 'Enabled' : 'Disabled',
              ),
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
        rows={sorted(rows)}
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
  if (key === 'author') return agent.created_by ? [agent.created_by] : []
  if (key === 'team') return agent.team ? [agent.team.slug] : []
  if (key === 'tag') return agent.tags.map((t) => t.slug)
  return [agent.enabled ? 'enabled' : 'disabled']
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

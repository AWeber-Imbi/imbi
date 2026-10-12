import { useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { AdminSection } from '@/components/admin/AdminSection'
import { agentsPath } from '@/components/agents/agentsNav'
import { AdminTable } from '@/components/ui/admin-table'
import { useHasPermission } from '@/hooks/useHasPermission'

import { stepIcon } from './stepStyle'
import type { StepType, WorkflowSummary } from './types'
import { StatusBadge } from './WorkflowStatusBadge'

interface WorkflowListProps {
  error: unknown
  loading: boolean
  stepTypes: StepType[]
  workflows: WorkflowSummary[]
}

export function WorkflowList({
  error,
  loading,
  stepTypes,
  workflows,
}: WorkflowListProps) {
  const navigate = useNavigate()
  const canCreate = useHasPermission('workflow:create')
  const [search, setSearch] = useState('')
  const labels = useMemo(
    () => Object.fromEntries(stepTypes.map((t) => [t.type, t.label])),
    [stepTypes],
  )

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return workflows
    return workflows.filter((w) =>
      [w.name, w.description, w.owner_team_slug]
        .join(' ')
        .toLowerCase()
        .includes(q),
    )
  }, [search, workflows])

  const dash = () => <span className="text-tertiary text-sm">—</span>

  return (
    <AdminSection
      createLabel="New workflow"
      error={error}
      errorTitle="Failed to load workflows"
      onCreate={
        canCreate ? () => navigate(agentsPath('workflows', 'new')) : undefined
      }
      onSearchChange={setSearch}
      search={search}
      searchPlaceholder="Search workflows"
    >
      <AdminTable
        columns={[
          {
            header: 'Name',
            key: 'name',
            render: (w) => (
              <div className="flex min-w-0 flex-col">
                <span className="text-sm font-medium">{w.name}</span>
                {w.description && (
                  <span className="text-tertiary max-w-90 truncate text-xs">
                    {w.description}
                  </span>
                )}
              </div>
            ),
          },
          {
            header: 'Trigger',
            key: 'trigger',
            render: (w) => (
              <TriggerCell labels={labels} types={w.trigger_types} />
            ),
          },
          { header: 'Last run', key: 'last', render: dash },
          {
            cellAlign: 'right',
            header: 'Runs 30d',
            headerAlign: 'right',
            key: 'runs',
            render: dash,
          },
          {
            header: 'Status',
            key: 'status',
            render: (w) => <StatusBadge status={w.status} />,
          },
        ]}
        emptyMessage={
          workflows.length === 0
            ? 'No workflows yet.'
            : 'No workflows match that search.'
        }
        getRowHref={(w) => agentsPath('workflows', w.slug)}
        getRowKey={(w) => w.slug}
        getRowLabel={(w) => w.name}
        loading={loading}
        rows={rows}
      />
    </AdminSection>
  )
}

function TriggerCell({
  labels,
  types,
}: {
  labels: Record<string, string>
  types: string[]
}) {
  if (types.length === 0) {
    return <span className="text-tertiary text-sm">No trigger</span>
  }
  const Icon = stepIcon(types[0], 'trigger')
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="bg-tertiary text-secondary flex size-6 shrink-0 items-center justify-center rounded-md">
        <Icon className="size-3.5" />
      </span>
      <span className="truncate text-sm">
        {types.map((t) => labels[t] ?? t).join(', ')}
      </span>
    </div>
  )
}

import { useState } from 'react'

import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  listScheduledTaskRuns,
  listScheduledTasks,
  pauseScheduledTask,
  resumeScheduledTask,
} from '@/api/scheduler'
import { AdminTable } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Switch } from '@/components/ui/switch'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAuth } from '@/hooks/useAuth'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { formatDateTime } from '@/lib/formatDate'
import type { ScheduledRun, ScheduledTask } from '@/types/scheduler'

import { AdminSection } from './AdminSection'
import { ScheduledJobDetail } from './scheduled-jobs/ScheduledJobDetail'
import { ScheduledJobForm } from './scheduled-jobs/ScheduledJobForm'
import {
  isFailing,
  jobDisplayState,
  targetSummary,
  taskPermissions,
  triggerSummary,
} from './scheduled-jobs/scheduledJobs'
import { RecentRuns, StatePill } from './scheduled-jobs/StatePill'

type Filter = 'all' | 'failing' | 'paused' | 'system'

const FILTERS: [Filter, string][] = [
  ['all', 'All'],
  ['system', 'System'],
  ['failing', 'Last run failed'],
  ['paused', 'Paused'],
]

const RECENT_RUNS = 8

// The admin "Scheduled jobs" section. The scheduler calls these tasks; the
// UI says "jobs" so they are not confused with agent tasks.
export function ScheduledJobsManagement() {
  const { slug, viewMode } = useAdminNav()
  if (viewMode === 'create') return <ScheduledJobForm slug={null} />
  if (viewMode === 'edit' && slug) return <ScheduledJobForm slug={slug} />
  if (viewMode === 'detail' && slug) return <ScheduledJobDetail slug={slug} />
  return <ScheduledJobsList />
}

function ScheduledJobsList() {
  const { detailPath, goToCreate } = useAdminNav()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const canCreate = useHasPermission('scheduled_task:create')
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')

  const tasksQuery = useQuery({
    queryFn: ({ signal }) => listScheduledTasks(signal),
    queryKey: ['scheduler', 'tasks'],
  })
  const tasks = tasksQuery.data ?? []

  // Run history needs ownership (or scheduled_task:admin), so only the jobs
  // the caller may read are asked for. The others show no last state.
  const can = new Map(tasks.map((t) => [t.slug, taskPermissions(user, t)]))
  const readable = tasks.filter((t) => can.get(t.slug)!.readRuns)
  const runResults = useQueries({
    queries: readable.map((t) => ({
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        listScheduledTaskRuns(t.slug, RECENT_RUNS, signal),
      queryKey: ['scheduler', 'runs', t.slug, RECENT_RUNS],
      staleTime: 30_000,
    })),
  })
  const runsBySlug = new Map<string, ScheduledRun[] | undefined>(
    readable.map((t, i) => [t.slug, runResults[i].data]),
  )
  const stateOf = (t: ScheduledTask) =>
    jobDisplayState(t, runsBySlug.get(t.slug))

  const toggle = useMutation({
    mutationFn: (t: ScheduledTask) =>
      t.enabled ? pauseScheduledTask(t.slug) : resumeScheduledTask(t.slug),
    onError: (error) =>
      toast.error(extractApiErrorDetail(error, 'Could not change the job')),
    onSuccess: (t) => {
      toast.success(t.enabled ? `Resumed ${t.slug}` : `Paused ${t.slug}`)
      queryClient.setQueryData(['scheduler', 'task', t.slug], t)
      return queryClient.invalidateQueries({ queryKey: ['scheduler', 'tasks'] })
    },
  })

  const matches: Record<Filter, (t: ScheduledTask) => boolean> = {
    all: () => true,
    failing: (t) => isFailing(stateOf(t)),
    paused: (t) => !t.enabled,
    system: (t) => t.kind === 'system',
  }
  const query = search.toLowerCase()
  const rows = tasks.filter(
    (t) =>
      matches[filter](t) && `${t.name} ${t.slug}`.toLowerCase().includes(query),
  )

  return (
    <AdminSection
      createLabel="New job"
      error={tasksQuery.error}
      errorTitle="Failed to load scheduled jobs"
      headerExtras={
        <SegmentedControl
          ariaLabel="Filter"
          onValueChange={(v) => setFilter(v as Filter)}
          value={filter}
        >
          {FILTERS.map(([key, label]) => (
            <SegmentedControlItem key={key} value={key}>
              {label}
              <span className="font-medium">
                {tasks.filter(matches[key]).length}
              </span>
            </SegmentedControlItem>
          ))}
        </SegmentedControl>
      }
      onCreate={canCreate ? goToCreate : undefined}
      onSearchChange={setSearch}
      search={search}
      searchPlaceholder="Search jobs"
    >
      <AdminTable
        columns={[
          {
            header: 'Job',
            key: 'job',
            render: (t) => (
              <div>
                <div className="text-primary flex items-center gap-2 font-medium">
                  {t.name}
                  {t.kind === 'system' && (
                    <Badge variant="neutral">system</Badge>
                  )}
                </div>
                <div className="text-tertiary font-mono text-xs">{t.slug}</div>
              </div>
            ),
          },
          {
            header: 'Schedule',
            key: 'schedule',
            render: (t) => (
              <div>
                {triggerSummary(t.trigger)}
                <div className="text-tertiary text-xs">{t.timezone}</div>
              </div>
            ),
          },
          {
            header: 'Calls',
            key: 'calls',
            render: (t) => (
              <span className="font-mono text-xs">{targetSummary(t)}</span>
            ),
          },
          {
            header: 'Next run',
            key: 'next',
            render: (t) =>
              t.enabled ? (
                formatDateTime(t.next_run_at)
              ) : (
                <span className="text-tertiary">Paused</span>
              ),
          },
          {
            header: 'Last run',
            key: 'last',
            render: (t) => {
              const state = stateOf(t)
              return state ? <StatePill state={state} /> : '—'
            },
          },
          {
            header: 'Recent',
            key: 'recent',
            render: (t) => <RecentRuns runs={runsBySlug.get(t.slug) ?? []} />,
          },
          {
            header: 'On',
            interactive: true,
            key: 'enabled',
            render: (t) => (
              <Switch
                aria-label={`Enable ${t.name}`}
                checked={t.enabled}
                disabled={!can.get(t.slug)?.edit || toggle.isPending}
                onCheckedChange={() => toggle.mutate(t)}
              />
            ),
          },
        ]}
        emptyMessage="No jobs match this filter."
        getRowHref={(t) => detailPath(t.slug)}
        getRowKey={(t) => t.slug}
        getRowLabel={(t) => t.name}
        loading={tasksQuery.isLoading}
        rows={rows}
      />
    </AdminSection>
  )
}

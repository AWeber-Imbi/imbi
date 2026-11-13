import { type ReactNode, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pause, Pencil, Play, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  deleteScheduledTask,
  dryRunScheduledTask,
  getScheduledTask,
  listScheduledTaskRuns,
  pauseScheduledTask,
  resumeScheduledTask,
  runScheduledTask,
} from '@/api/scheduler'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Sk } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAuth } from '@/hooks/useAuth'
import { extractApiErrorDetail } from '@/lib/apiError'
import { formatDateTime } from '@/lib/formatDate'
import type { ScheduledRun, ScheduledTask } from '@/types/scheduler'

import {
  CODE_BLOCK,
  jobDisplayState,
  NO_PERMISSIONS,
  runDisplayState,
  taskPermissions,
  triggerSummary,
} from './scheduledJobs'
import { StatePill } from './StatePill'

const HISTORY_LIMIT = 50

export function ScheduledJobDetail({ slug }: { slug: string }) {
  const { goToEdit, goToList } = useAdminNav()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<string>()
  const [confirmDelete, setConfirmDelete] = useState(false)

  const taskQuery = useQuery({
    queryFn: ({ signal }) => getScheduledTask(slug, signal),
    queryKey: ['scheduler', 'task', slug],
  })
  const task = taskQuery.data
  const can = task ? taskPermissions(user, task) : NO_PERMISSIONS

  const runsQuery = useQuery({
    enabled: can.readRuns,
    queryFn: ({ signal }) => listScheduledTaskRuns(slug, HISTORY_LIMIT, signal),
    queryKey: ['scheduler', 'runs', slug, HISTORY_LIMIT],
  })

  // Run now and pause change the runs and the task; the definition, and so
  // the dry run, stay the same.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['scheduler', 'tasks'] }),
      queryClient.invalidateQueries({ queryKey: ['scheduler', 'task', slug] }),
      queryClient.invalidateQueries({ queryKey: ['scheduler', 'runs', slug] }),
    ])
  const onError = (error: unknown) =>
    toast.error(extractApiErrorDetail(error, 'The request failed'))

  const runNow = useMutation({
    mutationFn: () => runScheduledTask(slug),
    onError,
    onSuccess: (run) => {
      toast.success(`Ran ${slug}: ${run.state}`)
      setTab('runs')
      return refresh()
    },
  })
  const toggle = useMutation({
    mutationFn: () =>
      task?.enabled ? pauseScheduledTask(slug) : resumeScheduledTask(slug),
    onError,
    onSuccess: (t) => {
      toast.success(t.enabled ? 'Resumed' : 'Paused')
      return refresh()
    },
  })
  const remove = useMutation({
    mutationFn: () => deleteScheduledTask(slug),
    onError,
    onSuccess: () => {
      toast.success(`Deleted ${slug}`)
      for (const key of ['task', 'runs', 'dry-run']) {
        queryClient.removeQueries({ queryKey: ['scheduler', key, slug] })
      }
      goToList()
      return queryClient.invalidateQueries({ queryKey: ['scheduler', 'tasks'] })
    },
  })

  if (taskQuery.error) {
    return <ErrorBanner error={taskQuery.error} title="Failed to load job" />
  }
  if (!task) return <Sk h={160} w="100%" />

  const runs = runsQuery.data
  const state = jobDisplayState(task, runs)
  const isSystem = task.kind === 'system'

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-4 p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h2 className="text-primary flex items-center gap-2 text-xl font-medium">
                {task.name}
                {isSystem && <Badge variant="neutral">system</Badge>}
              </h2>
              <div className="text-secondary mt-1 flex flex-wrap items-center gap-3 text-sm">
                <span className="font-mono">{task.slug}</span>
                <span>
                  {triggerSummary(task.trigger)} · {task.timezone}
                </span>
                <span>
                  Next:{' '}
                  {task.enabled ? formatDateTime(task.next_run_at) : 'paused'}
                </span>
                {state && <StatePill state={state} />}
              </div>
              {task.description && (
                <p className="text-secondary mt-2 text-sm">
                  {task.description}
                </p>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {can.run && (
                <Button
                  className="bg-action text-action-foreground hover:bg-action-hover"
                  disabled={runNow.isPending}
                  onClick={() => runNow.mutate()}
                >
                  <Play className="size-4" />
                  {runNow.isPending ? 'Running...' : 'Run now'}
                </Button>
              )}
              {can.edit && (
                <Button
                  disabled={toggle.isPending}
                  onClick={() => toggle.mutate()}
                  variant="outline"
                >
                  {task.enabled ? (
                    <Pause className="size-4" />
                  ) : (
                    <Play className="size-4" />
                  )}
                  {task.enabled ? 'Pause' : 'Resume'}
                </Button>
              )}
              {can.edit && (
                <Button onClick={() => goToEdit(slug)} variant="outline">
                  <Pencil className="size-4" />
                  Edit
                </Button>
              )}
              {can.delete && (
                <Button
                  className="text-danger"
                  onClick={() => setConfirmDelete(true)}
                  variant="outline"
                >
                  <Trash2 className="size-4" />
                  Delete
                </Button>
              )}
            </div>
          </div>
          {isSystem && (
            <div className="bg-info text-info rounded-md px-3 py-2 text-sm">
              System job. Imbi creates it when it is missing and never
              overwrites your changes. If you delete it, Imbi creates it again
              with the default schedule at the next scheduler start.
            </div>
          )}
        </CardContent>
      </Card>

      <Tabs
        onValueChange={setTab}
        value={tab ?? (can.readRuns ? 'runs' : 'definition')}
      >
        <TabsList className="mb-4">
          {can.readRuns && <TabsTrigger value="runs">Run history</TabsTrigger>}
          <TabsTrigger value="definition">Definition</TabsTrigger>
          <TabsTrigger value="dry-run">Dry run</TabsTrigger>
        </TabsList>
        {can.readRuns && (
          <TabsContent value="runs">
            <RunHistory error={runsQuery.error} runs={runs} />
          </TabsContent>
        )}
        <TabsContent value="definition">
          <Definition task={task} />
        </TabsContent>
        <TabsContent value="dry-run">
          <DryRunPanel slug={slug} />
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        confirmLabel="Delete job"
        description={
          'The job stops firing. Its run history stays readable to admins.' +
          (isSystem
            ? ' This is a system job, so the scheduler creates it again with' +
              ' the default schedule when it next starts. To stop it for' +
              ' good, pause it instead.'
            : '')
        }
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false)
          remove.mutate()
        }}
        open={confirmDelete}
        title={`Delete ${task.name}?`}
      />
    </div>
  )
}

function Box({ children, title }: { children: ReactNode; title: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-tertiary mb-2 text-xs font-medium tracking-wider uppercase">
          {title}
        </p>
        {children}
      </CardContent>
    </Card>
  )
}

function Definition({ task }: { task: ScheduledTask }) {
  const exec = task.execution
  const rows = (items: [string, ReactNode][]) => (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {items.map(([k, v]) => (
        <div className="contents" key={k}>
          <dt className="text-secondary">{k}</dt>
          <dd className="text-primary">{v}</dd>
        </div>
      ))}
    </dl>
  )
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Box title="When">
        {rows([
          ['Trigger', `${task.trigger.kind} · ${triggerSummary(task.trigger)}`],
          ...(task.trigger.kind === 'cron'
            ? [
                [
                  'Expression',
                  <code key="e">{task.trigger.expression}</code>,
                ] as [string, ReactNode],
              ]
            : []),
          ['Timezone', task.timezone],
          [
            'Next run',
            task.enabled ? formatDateTime(task.next_run_at) : 'Paused',
          ],
          ['Last run', formatDateTime(task.last_run_at)],
        ])}
      </Box>
      <Box title="Who">
        {rows([
          [
            'Runs as',
            task.identity
              ? `${task.identity.subject} (${task.identity.kind})`
              : 'No identity (gateway)',
          ],
          ['Accountable', task.updated_by ?? task.created_by],
          ['Created by', task.created_by],
          ...(task.organization
            ? [['Organization', task.organization] as [string, ReactNode]]
            : []),
        ])}
      </Box>
      <Box title="What">
        <pre className={CODE_BLOCK}>{JSON.stringify(task.target, null, 2)}</pre>
      </Box>
      <Box title="On failure">
        {rows([
          ['Timeout', `${exec.timeout} s`],
          ['Retries', `${exec.retries} · ${exec.retry_backoff}`],
          ['Concurrent runs', exec.max_running_instances],
          [
            'Late-start grace',
            exec.misfire_grace_time === null
              ? 'None'
              : `${exec.misfire_grace_time} s`,
          ],
        ])}
      </Box>
    </div>
  )
}

function DryRunPanel({ slug }: { slug: string }) {
  const { data, error, isLoading } = useQuery({
    queryFn: ({ signal }) => dryRunScheduledTask(slug, signal),
    queryKey: ['scheduler', 'dry-run', slug],
    // Changes only when the definition does; a save invalidates it.
    staleTime: Infinity,
  })
  if (error) return <ErrorBanner error={error} title="Dry run failed" />
  if (isLoading || !data) return <Sk h={120} w="100%" />
  const query = new URLSearchParams(data.query).toString()
  const request = [
    `${data.method} ${data.url}${query ? `?${query}` : ''}`,
    ...Object.entries(data.headers).map(([k, v]) => `${k}: ${v}`),
    ...(data.body ? ['', JSON.stringify(data.body, null, 2)] : []),
  ].join('\n')
  return (
    <div className="space-y-3">
      <p className="text-secondary text-sm">
        Renders the request and resolves the identity without sending anything.
      </p>
      {data.would_run ? (
        <pre className={CODE_BLOCK}>{request}</pre>
      ) : (
        <ErrorBanner message={data.reason} title="This job would not run" />
      )}
      <p className="text-tertiary text-xs">
        Identity: {data.principal_name || 'none'}
        {data.identity_kind ? ` (${data.identity_kind})` : ''}
        {data.identity_kind && data.identity_kind !== 'none'
          ? data.bearer_resolved
            ? ', token resolved'
            : ', token not resolved'
          : ''}
      </p>
    </div>
  )
}

function RunHistory({
  error,
  runs,
}: {
  error: unknown
  runs: ScheduledRun[] | undefined
}) {
  if (error) return <ErrorBanner error={error} title="Failed to load runs" />
  if (!runs) return <Sk h={120} w="100%" />
  if (!runs.length) {
    return <p className="text-secondary text-sm">This job has not run yet.</p>
  }
  return (
    <div className="space-y-3">
      {runs.some((r) => runDisplayState(r) === 'busy') && (
        <div className="bg-warning text-warning rounded-md px-3 py-2 text-sm">
          A run got &quot;Already running&quot;: the previous run had not
          finished when this one fired. The work itself did not fail. If this
          happens often, make the interval longer.
        </div>
      )}
      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="text-secondary text-left text-xs">
              <tr className="border-tertiary border-b">
                <th className="px-4 py-2 font-medium">Fired</th>
                <th className="px-4 py-2 font-medium">State</th>
                <th className="px-4 py-2 font-medium">Duration</th>
                <th className="px-4 py-2 font-medium">Attempts</th>
                <th className="px-4 py-2 font-medium">Response</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const response = [
                  run.http_status ? String(run.http_status) : '',
                  run.response_excerpt || run.error_message,
                ]
                  .filter(Boolean)
                  .join(' ')
                return (
                  <tr
                    className="border-tertiary border-b last:border-0"
                    key={run.run_id}
                  >
                    <td className="px-4 py-2 whitespace-nowrap">
                      {formatDateTime(run.fired_at)}
                      <div className="text-tertiary font-mono text-xs">
                        {run.run_id}
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      <StatePill state={runDisplayState(run)} />
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      {run.state === 'running'
                        ? '—'
                        : `${(run.duration_ms / 1000).toFixed(2)} s`}
                    </td>
                    <td className="px-4 py-2">{run.attempt}</td>
                    <td className="max-w-md px-4 py-2">
                      <div
                        className="truncate font-mono text-xs"
                        title={response}
                      >
                        {response || '—'}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

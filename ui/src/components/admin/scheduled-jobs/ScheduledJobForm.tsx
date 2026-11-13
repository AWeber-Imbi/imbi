import { type ReactNode, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  createScheduledTask,
  getScheduledTask,
  patchScheduledTask,
} from '@/api/scheduler'
import { FormHeader } from '@/components/admin/form-header'
import { Card, CardContent } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Sk } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { useAdminNav } from '@/hooks/useAdminNav'
import type {
  ExecutionPolicy,
  HttpMethod,
  ScheduledTask,
  ScheduledTaskCreate,
  Trigger,
} from '@/types/scheduler'

import { buildTaskPatch, CODE_BLOCK } from './scheduledJobs'

// An api target runs as the scheduler's own service account, the only
// identity the scheduler accepts (settings.Scheduler.sa_slug, default
// permissions.SCHEDULER_ACCOUNT). A deployment that renames it gets a 422
// on create that names the problem.
const SCHEDULER_IDENTITY = {
  kind: 'service_account',
  subject: 'imbi-scheduler',
} as const

const DEFAULT_TRIGGERS: Record<Trigger['kind'], Trigger> = {
  calendar: { at_time: '09:00', days: 1, kind: 'calendar' },
  cron: { expression: '0 6 * * *', kind: 'cron' },
  date: { kind: 'date', run_at: '' },
  interval: { hours: 1, kind: 'interval' },
}

const NEW_JOB: ScheduledTaskCreate = {
  description: null,
  enabled: true,
  execution: {
    max_running_instances: 1,
    misfire_grace_time: 300,
    retries: 0,
    retry_backoff: 'exponential',
    timeout: 120,
  },
  identity: SCHEDULER_IDENTITY,
  kind: 'user',
  name: '',
  slug: '',
  target: { kind: 'api', method: 'POST', path: '/' },
  timezone: 'UTC',
  trigger: DEFAULT_TRIGGERS.cron,
}

const TIMEZONES = [
  'UTC',
  ...((
    Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf?.('timeZone') ?? []),
]

const SECONDS = { days: 86400, hours: 3600, minutes: 60, seconds: 1 }
const CALENDAR_DAYS = { days: 1, weeks: 7 }

const toSlug = (value: string) =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 64)

// The largest unit that divides `total` evenly, so a stored step reads back
// as "6 hours" rather than "21600 seconds".
function asSingleUnit<U extends string>(
  total: number,
  units: Record<U, number>,
): [number, U] {
  const entries = Object.entries(units) as [U, number][]
  const [unit, size] = entries
    .sort((a, b) => b[1] - a[1])
    .find(([, s]) => total % s === 0)!
  return [total / size, unit]
}

const json = (value: unknown) => (value ? JSON.stringify(value, null, 2) : '')

export function ScheduledJobForm({ slug }: { slug: null | string }) {
  const { data: task, error } = useQuery({
    enabled: !!slug,
    queryFn: ({ signal }) => getScheduledTask(slug!, signal),
    queryKey: ['scheduler', 'task', slug],
  })
  if (error) return <ErrorBanner error={error} title="Failed to load job" />
  if (slug && !task) return <Sk h={320} w="100%" />
  return <JobForm key={task?.slug ?? 'new'} task={task ?? null} />
}

// A native select, for short fixed lists.
function Choice<T extends string>({
  onChange,
  options,
  value,
}: {
  onChange: (value: T) => void
  options: T[]
  value: T
}) {
  return (
    <select
      className="border-input bg-background h-9 rounded-md border px-2 text-sm"
      onChange={(e) => onChange(e.target.value as T)}
      value={value}
    >
      {options.map((o) => (
        <option key={o}>{o}</option>
      ))}
    </select>
  )
}

// The "Every N <unit>" pair shared by the interval and calendar triggers.
function EveryUnit({
  n,
  onStep,
  unit,
  units,
}: {
  n: number
  onStep: (count: number, unit: string) => void
  unit: string
  units: string[]
}) {
  return (
    <>
      <Field label="Every">
        <Input
          min={1}
          onChange={(e) => onStep(+e.target.value, unit)}
          type="number"
          value={n}
        />
      </Field>
      <Field label="Unit">
        <Choice onChange={(u) => onStep(n, u)} options={units} value={unit} />
      </Field>
    </>
  )
}

function Field({
  children,
  hint,
  label,
}: {
  children: ReactNode
  hint?: ReactNode
  label: string
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
      <Label>
        <span className="mb-1.5 block">{label}</span>
        {children}
      </Label>
      {hint && <span className="text-tertiary text-xs">{hint}</span>}
    </div>
  )
}

function JobForm({ task }: { task: null | ScheduledTask }) {
  const { goToDetail, goToList } = useAdminNav()
  const queryClient = useQueryClient()
  const isSystem = task?.kind === 'system'
  // On edit the draft carries the server-owned fields too; buildTaskPatch
  // sends only the editable ones.
  const [draft, setDraft] = useState<ScheduledTaskCreate>(task ?? NEW_JOB)
  const [bodyText, setBodyText] = useState(() =>
    json(
      draft.target.kind === 'api' ? draft.target.body : draft.target.payload,
    ),
  )
  const [formError, setFormError] = useState('')

  const set = (update: Partial<ScheduledTaskCreate>) =>
    setDraft((d) => ({ ...d, ...update }))
  const setTrigger = (trigger: Trigger) => set({ trigger })
  const setExecution = (update: Partial<ExecutionPolicy>) =>
    set({ execution: { ...draft.execution, ...update } })

  const save = useMutation({
    mutationFn: async (body: ScheduledTaskCreate) => {
      if (!task) return createScheduledTask(body)
      const operations = buildTaskPatch(task, body)
      return operations.length
        ? patchScheduledTask(task.slug, operations)
        : task
    },
    onSuccess: (saved) => {
      toast.success(task ? 'Saved' : `Created ${saved.slug}`)
      void queryClient.invalidateQueries({ queryKey: ['scheduler'] })
      goToDetail(saved.slug)
    },
  })

  const handleSave = () => {
    if (!draft.name.trim() || !draft.slug.trim()) {
      setFormError('Give the job a name and a slug.')
      return
    }
    let parsed: null | Record<string, unknown> = null
    try {
      parsed = bodyText.trim() ? JSON.parse(bodyText) : null
    } catch {
      setFormError('The body is not valid JSON.')
      return
    }
    const target =
      draft.target.kind === 'api'
        ? { ...draft.target, body: parsed }
        : { ...draft.target, payload: parsed ?? {} }
    setFormError('')
    save.mutate({
      ...draft,
      description: draft.description?.trim() || null,
      name: draft.name.trim(),
      // An unedited target goes back as it came, so it is not patched.
      target: isSystem ? draft.target : target,
    })
  }

  const t = draft.trigger
  const target = draft.target
  const exec = draft.execution

  return (
    <div className="max-w-3xl space-y-6">
      <FormHeader
        createLabel="Create job"
        isEditing={!!task}
        isLoading={save.isPending}
        onCancel={() => (task ? goToDetail(task.slug) : goToList())}
        onSave={handleSave}
        subtitle={
          isSystem
            ? 'System job: you can change the schedule, timezone, and failure policy. The target is fixed.'
            : undefined
        }
        title={task ? 'Edit job' : 'New job'}
      />

      {(formError || save.error) && (
        <ErrorBanner
          error={save.error}
          message={formError || undefined}
          title="Could not save the job"
        />
      )}

      <Section title="Job">
        <div className="flex gap-4">
          <Field label="Name">
            <Input
              disabled={isSystem}
              onChange={(e) =>
                set({
                  name: e.target.value,
                  ...(task ? {} : { slug: toSlug(e.target.value) }),
                })
              }
              placeholder="Nightly dependency audit"
              value={draft.name}
            />
          </Field>
          <Field label="Slug">
            <Input
              className="font-mono"
              disabled={!!task}
              onChange={(e) => set({ slug: toSlug(e.target.value) })}
              placeholder="nightly-dependency-audit"
              value={draft.slug}
            />
          </Field>
        </div>
        <Field label="Description">
          <Input
            disabled={isSystem}
            onChange={(e) => set({ description: e.target.value })}
            value={draft.description ?? ''}
          />
        </Field>
      </Section>

      <Section title="When">
        <SegmentedControl
          ariaLabel="Trigger"
          onValueChange={(kind) =>
            setTrigger(DEFAULT_TRIGGERS[kind as Trigger['kind']])
          }
          value={t.kind}
        >
          <SegmentedControlItem value="cron">Cron</SegmentedControlItem>
          <SegmentedControlItem value="interval">Interval</SegmentedControlItem>
          <SegmentedControlItem value="calendar">Calendar</SegmentedControlItem>
          <SegmentedControlItem value="date">Once</SegmentedControlItem>
        </SegmentedControl>
        <TriggerFields onChange={setTrigger} trigger={t} />
        <Field label="Timezone">
          <Input
            list="scheduler-timezones"
            onChange={(e) => set({ timezone: e.target.value })}
            value={draft.timezone}
          />
          <datalist id="scheduler-timezones">
            {TIMEZONES.map((z) => (
              <option key={z} value={z} />
            ))}
          </datalist>
        </Field>
      </Section>

      <Section title="What it calls">
        {isSystem ? (
          <pre className={CODE_BLOCK}>{json(target)}</pre>
        ) : (
          <>
            <SegmentedControl
              ariaLabel="Target"
              onValueChange={(kind) => {
                setBodyText('')
                set(
                  kind === 'api'
                    ? {
                        identity: SCHEDULER_IDENTITY,
                        target: { kind: 'api', method: 'POST', path: '/' },
                      }
                    : {
                        identity: null,
                        target: {
                          kind: 'gateway',
                          payload: {},
                          webhook_id: '',
                        },
                      },
                )
              }}
              value={target.kind}
            >
              <SegmentedControlItem value="api">Imbi API</SegmentedControlItem>
              <SegmentedControlItem value="gateway">
                Gateway webhook
              </SegmentedControlItem>
            </SegmentedControl>
            {target.kind === 'api' ? (
              <>
                <div className="flex gap-4">
                  <Field label="Method">
                    <Choice
                      onChange={(method) =>
                        set({ target: { ...target, method } })
                      }
                      options={
                        [
                          'GET',
                          'POST',
                          'PUT',
                          'PATCH',
                          'DELETE',
                        ] as HttpMethod[]
                      }
                      value={target.method}
                    />
                  </Field>
                  <Field label="Organization">
                    <Input
                      className="font-mono"
                      onChange={(e) =>
                        set({
                          target: {
                            ...target,
                            organization: e.target.value || null,
                          },
                        })
                      }
                      placeholder="optional"
                      value={target.organization ?? ''}
                    />
                  </Field>
                </div>
                <Field
                  hint="Relative to the Imbi API. With an organization set, /organizations/<slug> is added in front."
                  label="Path"
                >
                  <Input
                    className="font-mono"
                    onChange={(e) =>
                      set({ target: { ...target, path: e.target.value } })
                    }
                    value={target.path}
                  />
                </Field>
              </>
            ) : (
              <Field label="Webhook ID">
                <Input
                  className="font-mono"
                  onChange={(e) =>
                    set({ target: { ...target, webhook_id: e.target.value } })
                  }
                  value={target.webhook_id}
                />
              </Field>
            )}
            <Field
              hint="Jinja2 templates allowed. Variables: now, task, run, last_run."
              label={target.kind === 'api' ? 'Body (JSON)' : 'Payload (JSON)'}
            >
              <Textarea
                className="font-mono text-xs"
                onChange={(e) => setBodyText(e.target.value)}
                rows={5}
                value={bodyText}
              />
            </Field>
            <p className="text-tertiary text-xs">
              {target.kind === 'api'
                ? 'Runs as the scheduler service account. You are recorded as accountable for every request.'
                : 'Gateway deliveries carry no identity; attribution comes from the payload.'}
            </p>
          </>
        )}
      </Section>

      <Section title="On failure">
        <div className="flex gap-4">
          <Field label="Timeout (s)">
            <Input
              min={1}
              onChange={(e) => setExecution({ timeout: +e.target.value })}
              type="number"
              value={exec.timeout}
            />
          </Field>
          <Field label="Retries">
            <Input
              min={0}
              onChange={(e) => setExecution({ retries: +e.target.value })}
              type="number"
              value={exec.retries}
            />
          </Field>
          <Field label="Backoff">
            <Choice
              onChange={(retry_backoff) => setExecution({ retry_backoff })}
              options={
                [
                  'none',
                  'linear',
                  'exponential',
                ] as ExecutionPolicy['retry_backoff'][]
              }
              value={exec.retry_backoff}
            />
          </Field>
          <Field label="Late-start grace (s)">
            <Input
              min={0}
              onChange={(e) =>
                setExecution({
                  misfire_grace_time:
                    e.target.value === '' ? null : +e.target.value,
                })
              }
              type="number"
              value={exec.misfire_grace_time ?? ''}
            />
          </Field>
        </div>
      </Section>
    </div>
  )
}

function Section({ children, title }: { children: ReactNode; title: string }) {
  return (
    <div>
      <p className="text-tertiary mb-2 text-xs font-medium tracking-wider uppercase">
        {title}
      </p>
      <Card>
        <CardContent className="space-y-4 p-4">{children}</CardContent>
      </Card>
    </div>
  )
}

function TriggerFields({
  onChange,
  trigger,
}: {
  onChange: (trigger: Trigger) => void
  trigger: Trigger
}) {
  switch (trigger.kind) {
    case 'calendar': {
      const [n, unit] = trigger.months
        ? [trigger.months, 'months']
        : asSingleUnit(
            (trigger.weeks ?? 0) * 7 + (trigger.days ?? 0),
            CALENDAR_DAYS,
          )
      const step = (count: number, u: string) =>
        onChange({
          at_time: trigger.at_time,
          end_at: trigger.end_at,
          kind: 'calendar',
          start_at: trigger.start_at,
          [u]: count,
        })
      return (
        <div className="flex gap-4">
          <EveryUnit
            n={n}
            onStep={step}
            unit={unit}
            units={['days', 'weeks', 'months']}
          />
          <Field
            hint="Keeps the wall-clock time across daylight saving changes."
            label="At time"
          >
            <Input
              onChange={(e) =>
                onChange({ ...trigger, at_time: e.target.value })
              }
              type="time"
              value={trigger.at_time.slice(0, 5)}
            />
          </Field>
        </div>
      )
    }
    case 'cron':
      return (
        <div className="flex gap-4">
          <Field hint="minute hour day month weekday" label="Cron expression">
            <Input
              className="font-mono"
              onChange={(e) =>
                onChange({ ...trigger, expression: e.target.value })
              }
              value={trigger.expression}
            />
          </Field>
          <Field label="Jitter (s)">
            <Input
              min={0}
              onChange={(e) =>
                onChange({
                  ...trigger,
                  jitter: e.target.value === '' ? null : +e.target.value,
                })
              }
              type="number"
              value={trigger.jitter ?? ''}
            />
          </Field>
        </div>
      )
    case 'date':
      return (
        <Field label="Run once at (UTC)">
          <Input
            onChange={(e) =>
              onChange({ kind: 'date', run_at: `${e.target.value}:00Z` })
            }
            type="datetime-local"
            value={trigger.run_at.slice(0, 16)}
          />
        </Field>
      )
    case 'interval': {
      const total = Object.entries(SECONDS).reduce(
        (sum, [u, s]) => sum + (trigger[u as keyof typeof SECONDS] ?? 0) * s,
        0,
      )
      const [n, unit] = asSingleUnit(total || 3600, SECONDS)
      const step = (count: number, u: string) =>
        onChange({
          end_at: trigger.end_at,
          kind: 'interval',
          start_at: trigger.start_at,
          [u]: count,
        })
      return (
        <div className="flex gap-4">
          <EveryUnit
            n={n}
            onStep={step}
            unit={unit}
            units={Object.keys(SECONDS)}
          />
        </div>
      )
    }
  }
}

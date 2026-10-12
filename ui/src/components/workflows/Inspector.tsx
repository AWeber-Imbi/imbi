import { type ReactNode, useMemo } from 'react'

import { Copy, Trash2 } from 'lucide-react'

import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

import { portsOf, type StepTypes } from './graph'
import { ParamsForm, SelectField } from './ParamsForm'
import { StatusBadge } from './RunPanel'
import { formatDuration, type StepResult } from './runs'
import { paramFields } from './schemaFields'
import { CATEGORY_TILE, stepIcon } from './stepStyle'
import type {
  ValidationIssue,
  WorkflowGraph,
  WorkflowNode,
  WorkflowWrite,
} from './types'
import { useSourceOptions } from './workflowQueries'

const KEY_PATTERN = /^[a-z][a-z0-9_]*$/

const CONCURRENCY = [
  { label: 'Unlimited', value: 'unlimited' },
  { label: 'One run at a time', value: 'one_at_a_time' },
  { label: 'One run per key', value: 'one_per_key' },
]

const ON_FAILURE = [
  { label: 'Notify the owner team', value: 'notify_owner_team' },
  { label: 'Do nothing', value: 'none' },
]

export type InspectorTab = 'output' | 'params'

export function EdgePanel({
  graph,
  index,
  onRemove,
  readOnly,
  types,
}: {
  graph: WorkflowGraph
  index: number
  onRemove: () => void
  readOnly: boolean
  types: StepTypes
}) {
  const edge = graph.edges[index]
  const from = graph.nodes.find((n) => n.id === edge?.source)
  const to = graph.nodes.find((n) => n.id === edge?.target)
  if (!edge || !from || !to) return null
  const port = portsOf(from, types)[edge.port]
  return (
    <div className="flex flex-col gap-4 p-4">
      <span className="font-medium">Connection</span>
      <div className="border-tertiary flex flex-col gap-0.5 rounded-md border p-2.5 text-sm">
        <span className="text-tertiary text-xs">From</span>
        <span className="font-medium">{from.title}</span>
        {port && <span className="text-tertiary text-xs">Output: {port}</span>}
      </div>
      <div className="border-tertiary flex flex-col gap-0.5 rounded-md border p-2.5 text-sm">
        <span className="text-tertiary text-xs">To</span>
        <span className="font-medium">{to.title}</span>
      </div>
      {!readOnly && (
        <button
          className="border-danger text-danger hover:bg-danger flex h-9 items-center justify-center gap-1.5 rounded-md border text-sm font-medium"
          onClick={onRemove}
          type="button"
        >
          <Trash2 className="size-3.5" />
          Remove connection
        </button>
      )}
    </div>
  )
}

export function NodePanel({
  graph,
  issues,
  node,
  onChange,
  onDelete,
  onDuplicate,
  onRemoveItem,
  onTab,
  orgSlug,
  readOnly,
  result,
  resultSource,
  tab,
  types,
}: {
  graph: WorkflowGraph
  issues: ValidationIssue[]
  node: WorkflowNode
  onChange: (patch: Partial<WorkflowNode>) => void
  onDelete: () => void
  onDuplicate: () => void
  onRemoveItem: (name: string, index: number) => void
  onTab: (tab: InspectorTab) => void
  orgSlug: string
  readOnly: boolean
  /** What the step did in the run or the test run on show. */
  result: null | StepResult
  /** Null when no run or test run is on show. */
  resultSource: 'run' | 'test' | null
  tab: InspectorTab
  types: StepTypes
}) {
  const type = types[node.type]
  const Icon = stepIcon(node.type, type?.category)
  const fields = useMemo(
    () => (type ? paramFields(type.params_schema) : []),
    [type],
  )
  const incoming = graph.edges.filter((e) => e.target === node.id).length
  const keyError = !KEY_PATTERN.test(node.key)
    ? 'Use lower case letters, digits, and _, starting with a letter.'
    : graph.nodes.some((n) => n.id !== node.id && n.key === node.key)
      ? 'Another step has this key.'
      : undefined

  return (
    <>
      <div className="border-tertiary flex items-center gap-2.5 border-b px-4 py-3.5">
        <span
          className={cn(
            'flex size-9 shrink-0 items-center justify-center rounded-md',
            CATEGORY_TILE[type?.category ?? 'logic'],
          )}
        >
          <Icon className="size-4.5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <input
            aria-label="Step title"
            className="hover:border-tertiary focus:border-amber-border -ml-1.25 h-6.5 rounded-sm border border-transparent bg-transparent px-1 font-medium outline-none"
            disabled={readOnly}
            onChange={(e) => onChange({ title: e.target.value })}
            value={node.title}
          />
          <span className="text-tertiary text-xs">
            {type?.label ?? node.type}
          </span>
        </div>
        {!readOnly && (
          <>
            <IconButton label="Duplicate" onClick={onDuplicate}>
              <Copy className="size-3.5" />
            </IconButton>
            <IconButton danger label="Delete step" onClick={onDelete}>
              <Trash2 className="size-3.5" />
            </IconButton>
          </>
        )}
      </div>
      <div className="border-tertiary flex gap-4 border-b px-4">
        {(
          [
            ['params', 'Parameters'],
            ['output', 'Output'],
          ] as const
        ).map(([value, label]) => (
          <button
            className={cn(
              '-mb-px h-9 border-b-2 text-sm font-medium',
              tab === value
                ? 'text-primary border-amber-border'
                : 'text-tertiary hover:text-primary border-transparent',
            )}
            key={value}
            onClick={() => onTab(value)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'output' ? (
        <OutputView result={result} source={resultSource} />
      ) : (
        <fieldset
          className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-auto p-4"
          disabled={readOnly}
        >
          <IssueList issues={issues} />
          <FormField
            description="Later steps use this name to read the step's output."
            error={keyError}
            htmlFor="workflow-node-key"
            label="Key"
            touched
          >
            <Input
              className="font-mono text-xs"
              id="workflow-node-key"
              onChange={(e) => onChange({ key: e.target.value })}
              value={node.key}
            />
          </FormField>
          <ParamsForm
            fields={fields}
            idPrefix={`workflow-node-${node.id}`}
            onChange={(name, value) =>
              onChange({ params: { ...node.params, [name]: value } })
            }
            onRemoveItem={onRemoveItem}
            orgSlug={orgSlug}
            params={node.params}
          />
          {incoming > 1 && (
            <FormField
              description="Any runs the step when the first connection arrives. All waits for every connection."
              htmlFor="workflow-node-join"
              label="Run when"
            >
              <SelectField
                id="workflow-node-join"
                onChange={(join) => onChange({ join: join as 'all' | 'any' })}
                options={[
                  { label: 'Any input arrives', value: 'any' },
                  { label: 'All inputs arrive', value: 'all' },
                ]}
                value={node.join}
              />
            </FormField>
          )}
        </fieldset>
      )}
    </>
  )
}

export function SettingsPanel({
  draft,
  issues,
  onChange,
  orgSlug,
  readOnly,
}: {
  draft: WorkflowWrite
  issues: ValidationIssue[]
  onChange: (patch: Partial<WorkflowWrite>) => void
  orgSlug: string
  readOnly: boolean
}) {
  const teams = useSourceOptions(orgSlug, 'team')
  const settings = draft.settings
  const setSettings = (patch: Partial<WorkflowWrite['settings']>) =>
    onChange({ settings: { ...settings, ...patch } })
  return (
    <>
      <div className="border-tertiary flex flex-col gap-0.5 border-b p-4">
        <span className="font-medium">Workflow settings</span>
        <span className="text-tertiary text-xs">
          Select a step to edit it. Drag steps in from the left.
        </span>
      </div>
      <fieldset
        className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-auto p-4"
        disabled={readOnly}
      >
        <IssueList issues={issues} />
        <FormField htmlFor="workflow-description" label="Description">
          <Textarea
            id="workflow-description"
            onChange={(e) => onChange({ description: e.target.value })}
            rows={3}
            value={draft.description}
          />
        </FormField>
        <FormField htmlFor="workflow-team" label="Owner team" required>
          <SelectField
            id="workflow-team"
            onChange={(owner_team_slug) => onChange({ owner_team_slug })}
            options={teams.options}
            value={draft.owner_team_slug}
          />
        </FormField>
        <FormField
          description="Extra runs wait in a queue behind the active one."
          htmlFor="workflow-concurrency"
          label="Concurrency"
        >
          <SelectField
            id="workflow-concurrency"
            onChange={(mode) =>
              setSettings({
                concurrency_key:
                  mode === 'one_per_key' ? settings.concurrency_key : null,
                concurrency_mode:
                  mode as WorkflowWrite['settings']['concurrency_mode'],
              })
            }
            options={CONCURRENCY}
            value={settings.concurrency_mode}
          />
        </FormField>
        {settings.concurrency_mode === 'one_per_key' && (
          <FormField
            description="A reference to the trigger payload, for example {{ trigger.service }}."
            htmlFor="workflow-concurrency-key"
            label="Concurrency key"
          >
            <Input
              className="font-mono text-xs"
              id="workflow-concurrency-key"
              onChange={(e) => setSettings({ concurrency_key: e.target.value })}
              value={settings.concurrency_key ?? ''}
            />
          </FormField>
        )}
        <FormField htmlFor="workflow-max-run" label="Max run time (minutes)">
          <Input
            id="workflow-max-run"
            min={1}
            onChange={(e) =>
              setSettings({
                max_run_time_seconds: Math.round(Number(e.target.value) * 60),
              })
            }
            type="number"
            value={settings.max_run_time_seconds / 60}
          />
        </FormField>
        <FormField htmlFor="workflow-on-failure" label="When a run fails">
          <SelectField
            id="workflow-on-failure"
            onChange={(on_failure) =>
              setSettings({
                on_failure:
                  on_failure as WorkflowWrite['settings']['on_failure'],
              })
            }
            options={ON_FAILURE}
            value={settings.on_failure}
          />
        </FormField>
      </fieldset>
    </>
  )
}

function IconButton({
  children,
  danger,
  label,
  onClick,
}: {
  children: ReactNode
  danger?: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      aria-label={label}
      className={cn(
        'flex size-7.5 items-center justify-center rounded-md',
        danger
          ? 'text-danger hover:bg-danger'
          : 'text-secondary hover:bg-secondary',
      )}
      onClick={onClick}
      title={label}
      type="button"
    >
      {children}
    </button>
  )
}

function IssueList({ issues }: { issues: ValidationIssue[] }) {
  if (issues.length === 0) return null
  return (
    <ul className="flex flex-col gap-1.5">
      {issues.map((issue, i) => (
        <li
          className={cn(
            'rounded-md px-2.5 py-1.5 text-xs',
            issue.severity === 'error'
              ? 'bg-danger text-danger'
              : 'bg-amber-bg text-amber-text',
          )}
          key={i}
        >
          {issue.message}
        </li>
      ))}
    </ul>
  )
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-tertiary text-xs">{label}</span>
      <pre className="bg-secondary rounded-md p-3 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}

function OutputView({
  result,
  source,
}: {
  result: null | StepResult
  source: 'run' | 'test' | null
}) {
  if (!result || result.status === 'skipped') {
    return (
      <p className="text-tertiary p-4 text-sm">
        {source === null
          ? 'Run a test to see what this step returns.'
          : result
            ? 'This step was skipped. The run took a different branch.'
            : source === 'test'
              ? 'This step did not run in the last test run. The run took a different branch.'
              : 'This step has not run yet.'}
      </p>
    )
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4">
      <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-1.5 text-sm">
        <dt className="text-tertiary">Status</dt>
        <dd>
          <StatusBadge status={result.status} />
        </dd>
        <dt className="text-tertiary">Duration</dt>
        <dd className="font-mono text-xs">
          {source === 'test' ? 'sample' : formatDuration(result.durationMs)}
        </dd>
        {result.branch && (
          <>
            <dt className="text-tertiary">Branch</dt>
            <dd className="font-medium">{result.branch}</dd>
          </>
        )}
        {result.error && (
          <>
            <dt className="text-tertiary">Error</dt>
            <dd className="text-danger font-mono text-xs">{result.error}</dd>
          </>
        )}
      </dl>
      {result.input && <JsonBlock label="Input" value={result.input} />}
      {result.output && <JsonBlock label="Output" value={result.output} />}
    </div>
  )
}

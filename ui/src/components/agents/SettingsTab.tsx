import { useQuery } from '@tanstack/react-query'

import { listEgressDestinations } from '@/api/endpoints'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { queryKeys } from '@/lib/queryKeys'

import { type SettingsDraft, SLA_OPTIONS } from './agentDraft'
import { Field } from './OverviewTab'

interface SettingsTabProps {
  errors: Record<string, string>
  onChange: (settings: SettingsDraft) => void
  orgSlug: string
  value: SettingsDraft
}

/** Operational limits. An empty field means no limit. */
export function SettingsTab({
  errors,
  onChange,
  orgSlug,
  value,
}: SettingsTabProps) {
  const set = (patch: Partial<SettingsDraft>) =>
    onChange({ ...value, ...patch })
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-3 gap-4">
        <Field
          error={errors.monthlyCostCap}
          help="Advisory only. Spend is not enforced yet."
          htmlFor="agent-cost-cap"
          label="Monthly cost cap"
        >
          <Input
            id="agent-cost-cap"
            inputMode="decimal"
            onChange={(e) => set({ monthlyCostCap: e.target.value })}
            placeholder="No cap"
            value={value.monthlyCostCap}
          />
        </Field>
        <Field
          error={errors.taskBudget}
          help="The default hard budget of each task. A task can only lower it."
          htmlFor="agent-task-budget"
          label="Task budget"
        >
          <Input
            id="agent-task-budget"
            inputMode="decimal"
            onChange={(e) => set({ taskBudget: e.target.value })}
            placeholder="No budget"
            value={value.taskBudget}
          />
        </Field>
        <Field
          error={errors.maxConcurrentTasks}
          htmlFor="agent-max-tasks"
          label="Max concurrent tasks"
        >
          <Input
            id="agent-max-tasks"
            inputMode="numeric"
            onChange={(e) => set({ maxConcurrentTasks: e.target.value })}
            placeholder="No limit"
            value={value.maxConcurrentTasks}
          />
        </Field>
        <Field
          error={errors.taskTimeout}
          help="For example 30m or 2h. A number with no unit is minutes."
          htmlFor="agent-timeout"
          label="Task timeout"
        >
          <Input
            id="agent-timeout"
            onChange={(e) => set({ taskTimeout: e.target.value })}
            placeholder="No limit"
            value={value.taskTimeout}
          />
        </Field>
        <Field
          error={errors.requiredLabels}
          help="A runner needs every label to run the tasks of this agent. Separate labels with commas."
          htmlFor="agent-labels"
          label="Required runner labels"
        >
          <Input
            id="agent-labels"
            onChange={(e) => set({ requiredLabels: e.target.value })}
            placeholder="Any runner"
            value={value.requiredLabels}
          />
        </Field>
        <Field
          help="How long a task may sit waiting on a person before it escalates."
          htmlFor="agent-sla"
          label="Human response SLA"
        >
          <Select
            onValueChange={(v) =>
              set({ responseSla: v as SettingsDraft['responseSla'] })
            }
            value={value.responseSla || undefined}
          >
            <SelectTrigger id="agent-sla">
              <SelectValue placeholder="Not set" />
            </SelectTrigger>
            <SelectContent>
              {SLA_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>
      <EgressField
        onChange={(egressDestinations) => set({ egressDestinations })}
        orgSlug={orgSlug}
        value={value.egressDestinations}
      />
    </div>
  )
}

/**
 * The egress destinations that the agent's runner pods may reach, in
 * addition to the global ones. A selected slug that the organization
 * can no longer use stays listed so that it can be removed.
 */
function EgressField({
  onChange,
  orgSlug,
  value,
}: {
  onChange: (slugs: string[]) => void
  orgSlug: string
  value: string[]
}) {
  const destinations = useQuery({
    queryFn: ({ signal }) => listEgressDestinations(orgSlug, signal),
    queryKey: queryKeys.egressDestinations(orgSlug),
  })
  const known = destinations.data ?? []
  const options = [
    ...known.map((d) => ({ name: d.name, slug: d.slug })),
    ...value
      .filter((slug) => !known.some((d) => d.slug === slug))
      .map((slug) => ({ name: 'Not available', slug })),
  ]
  return (
    <Field
      error={
        destinations.error ? 'Failed to load egress destinations' : undefined
      }
      help="Internal networks that the runner pods of this agent may reach. Global destinations apply to every agent."
      label="Egress destinations"
    >
      {options.length === 0 ? (
        <p className="text-tertiary text-sm">
          {destinations.isLoading ? 'Loading…' : 'No destinations available.'}
        </p>
      ) : (
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {options.map((o) => (
            <label className="flex items-center gap-2 text-sm" key={o.slug}>
              <Checkbox
                checked={value.includes(o.slug)}
                onCheckedChange={(on) =>
                  onChange(
                    on ? [...value, o.slug] : value.filter((s) => s !== o.slug),
                  )
                }
              />
              {o.name}
              <span className="text-tertiary font-mono text-xs">{o.slug}</span>
            </label>
          ))}
        </div>
      )}
    </Field>
  )
}

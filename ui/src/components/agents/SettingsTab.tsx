import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import { type SettingsDraft, SLA_OPTIONS } from './agentDraft'
import { Field } from './OverviewTab'

interface SettingsTabProps {
  errors: Record<string, string>
  onChange: (settings: SettingsDraft) => void
  value: SettingsDraft
}

/** Operational limits. An empty field means no limit. */
export function SettingsTab({ errors, onChange, value }: SettingsTabProps) {
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
    </div>
  )
}

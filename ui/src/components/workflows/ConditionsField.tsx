import { Plus, X } from 'lucide-react'

import { cn } from '@/lib/utils'

import {
  type Condition,
  conditionWarnings,
  isUnary,
  MAX_CONDITIONS,
} from './conditions'
import { SelectField } from './ParamsForm'
import { TemplateInput } from './ReferencePicker'
import type { ReferenceGroup } from './references'

export function ConditionsField({
  id,
  label,
  onChange,
  operators,
  references,
  value,
}: {
  id: string
  label: string
  onChange: (value: Condition[]) => void
  operators: { label: string; value: string }[]
  references: ReferenceGroup[]
  value: Condition[]
}) {
  const replace = (index: number, row: Condition) =>
    onChange(value.map((other, position) => (position === index ? row : other)))
  return (
    <div
      aria-label={label}
      className="flex flex-col gap-2"
      id={id}
      role="group"
    >
      {value.map((row, index) => (
        <ConditionRow
          id={`${id}-${index}`}
          key={index}
          label={`Condition ${index + 1}`}
          onChange={(next) => replace(index, next)}
          onRemove={() =>
            onChange(value.filter((_, position) => position !== index))
          }
          operators={operators}
          references={references}
          row={row}
        />
      ))}
      {value.length < MAX_CONDITIONS && (
        <button
          className="border-input text-secondary hover:border-amber-border hover:text-primary flex h-8.5 items-center justify-center gap-1.5 rounded-md border border-dashed text-sm"
          onClick={() =>
            onChange([...value, { a: '', b: '', operator: 'equals' }])
          }
          type="button"
        >
          <Plus className="size-3.5" />
          Add condition
        </button>
      )}
    </div>
  )
}

function ConditionRow({
  id,
  label,
  onChange,
  onRemove,
  operators,
  references,
  row,
}: {
  id: string
  label: string
  onChange: (row: Condition) => void
  onRemove: () => void
  operators: { label: string; value: string }[]
  references: ReferenceGroup[]
  row: Condition
}) {
  const warnings = conditionWarnings(row, references)
  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-md border p-2',
        warnings.length > 0 ? 'border-danger' : 'border-tertiary',
      )}
    >
      <label className="sr-only" htmlFor={`${id}-a`}>
        {`${label} value`}
      </label>
      <TemplateInput
        groups={references}
        id={`${id}-a`}
        multiline={false}
        onChange={(a) => onChange({ ...row, a: fromText(row.a, a) })}
        value={text(row.a)}
      />
      <div className="flex items-center gap-1.5">
        <div className="min-w-0 flex-1">
          <SelectField
            id={`${id}-operator`}
            label={`${label} operator`}
            onChange={(operator) => onChange(withOperator(row, operator))}
            options={operators}
            value={row.operator}
          />
        </div>
        <button
          aria-label={`Remove ${label.toLowerCase()}`}
          className="text-secondary hover:bg-secondary flex size-7 shrink-0 items-center justify-center rounded-md"
          onClick={onRemove}
          type="button"
        >
          <X className="size-3.5" />
        </button>
      </div>
      {!isUnary(row.operator) && (
        <>
          <label className="sr-only" htmlFor={`${id}-b`}>
            {`${label} compared value`}
          </label>
          <TemplateInput
            groups={references}
            id={`${id}-b`}
            multiline={false}
            onChange={(b) => onChange({ ...row, b: fromText(row.b, b) })}
            value={text(row.b)}
          />
        </>
      )}
      {warnings.map((warning) => (
        <p className="text-danger text-xs" key={warning}>
          {warning}
        </p>
      ))}
    </div>
  )
}

function fromText(previous: unknown, next: string): unknown {
  if (previous === undefined || previous === null) return next
  if (typeof previous === 'string') return next
  try {
    return JSON.parse(next)
  } catch {
    return next
  }
}

function text(value: unknown): string {
  if (value === undefined || value === null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function withOperator(row: Condition, operator: string): Condition {
  if (isUnary(operator)) return { a: row.a, operator }
  return { a: row.a, b: row.b ?? '', operator }
}

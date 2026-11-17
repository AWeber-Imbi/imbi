import { Plus, X } from 'lucide-react'

import { Input } from '@/components/ui/input'

import { nameError } from './outputFields'
import { SelectField } from './ParamsForm'
import type { ManualInput } from './runs'

/** A manual trigger's inputs: a name and a type each, like output fields. */
export function ManualInputsField({
  id,
  label,
  onChange,
  types,
  value,
}: {
  id: string
  label: string
  onChange: (value: ManualInput[]) => void
  types: { label: string; value: string }[]
  value: ManualInput[]
}) {
  const set = (index: number, patch: Partial<ManualInput>) =>
    onChange(value.map((v, i) => (i === index ? { ...v, ...patch } : v)))
  return (
    <div
      aria-label={label}
      className="flex flex-col gap-2"
      id={id}
      role="group"
    >
      {value.map((input, index) => {
        const error = nameError(input, value)
        const errorId = `${id}-${index}-name-error`
        return (
          <div
            className="border-tertiary flex flex-col gap-2 rounded-md border p-2"
            key={index}
          >
            <div className="flex items-center gap-1.5">
              <Input
                aria-describedby={error ? errorId : undefined}
                aria-invalid={error !== undefined}
                aria-label={`Input ${index + 1} name`}
                className="font-mono text-xs"
                onChange={(e) => set(index, { name: e.target.value })}
                value={input.name}
              />
              <div className="w-28 shrink-0">
                <SelectField
                  id={`${id}-${index}-type`}
                  label={`Input ${index + 1} type`}
                  onChange={(type) =>
                    set(index, { type: type as ManualInput['type'] })
                  }
                  options={types}
                  value={input.type}
                />
              </div>
              <button
                aria-label={`Remove input ${index + 1}`}
                className="text-secondary hover:bg-secondary flex size-7 shrink-0 items-center justify-center rounded-md"
                onClick={() => onChange(value.filter((_, i) => i !== index))}
                type="button"
              >
                <X className="size-3.5" />
              </button>
            </div>
            {error && (
              <p className="text-danger text-xs" id={errorId}>
                {error}
              </p>
            )}
          </div>
        )
      })}
      <button
        className="border-input text-secondary hover:border-amber-border hover:text-primary flex h-8.5 items-center justify-center gap-1.5 rounded-md border border-dashed text-sm"
        onClick={() => onChange([...value, { name: '', type: 'string' }])}
        type="button"
      >
        <Plus className="size-3.5" />
        Add input
      </button>
    </div>
  )
}

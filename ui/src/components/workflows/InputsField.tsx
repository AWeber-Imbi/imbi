import { useState } from 'react'

import { Plus, X } from 'lucide-react'

import { Input } from '@/components/ui/input'

import { TemplateInput } from './ReferencePicker'
import type { ReferenceGroup } from './references'

/** The most inputs of a script step (`MAX_INPUTS` of the registry). */
export const MAX_INPUTS = 20

const NAME = /^[a-z][a-z0-9_]*$/

/** The lowercase names of Python's `keyword.kwlist`; the API refuses them. */
const KEYWORDS = new Set([
  'and',
  'as',
  'assert',
  'async',
  'await',
  'break',
  'class',
  'continue',
  'def',
  'del',
  'elif',
  'else',
  'except',
  'finally',
  'for',
  'from',
  'global',
  'if',
  'import',
  'in',
  'is',
  'lambda',
  'nonlocal',
  'not',
  'or',
  'pass',
  'raise',
  'return',
  'try',
  'while',
  'with',
  'yield',
])

interface Row {
  key: string
  name: string
  value: unknown
}

/**
 * The inputs of a script step: each name becomes a global of the script.
 * A value is text with references; one whole reference keeps its type.
 * A row with no name is kept here only, until it has one.
 */
export function InputsField({
  id,
  label,
  onChange,
  references,
  value,
}: {
  id: string
  label: string
  onChange: (value: Record<string, unknown>) => void
  references: ReferenceGroup[]
  value: Record<string, unknown>
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    Object.entries(value).map(([name, item]) => ({
      key: crypto.randomUUID(),
      name,
      value: item,
    })),
  )
  const update = (next: Row[]) => {
    setRows(next)
    const named = next.filter((row) => row.name)
    // A repeated name stays local: a map would drop one of the values.
    if (new Set(named.map((row) => row.name)).size !== named.length) return
    onChange(Object.fromEntries(named.map((row) => [row.name, row.value])))
  }
  const set = (index: number, patch: Partial<Row>) =>
    update(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  const names = rows.map((row) => row.name)
  return (
    <div
      aria-label={label}
      className="flex flex-col gap-2"
      id={id}
      role="group"
    >
      {rows.map((row, i) => {
        const error = nameError(row.name, names.indexOf(row.name) !== i)
        return (
          <div className="flex flex-col gap-1" key={row.key}>
            <div className="flex items-center gap-1.5">
              <Input
                aria-invalid={error !== null}
                aria-label={`Input ${i + 1} name`}
                className="h-8.5 w-32 shrink-0 font-mono text-xs"
                onChange={(e) => set(i, { name: e.target.value })}
                placeholder="name"
                value={row.name}
              />
              <div className="min-w-0 flex-1">
                <label className="sr-only" htmlFor={`${id}-${i}-value`}>
                  {`Input ${i + 1} value`}
                </label>
                <TemplateInput
                  groups={references}
                  id={`${id}-${i}-value`}
                  multiline={false}
                  onChange={(text) => set(i, { value: text })}
                  value={
                    typeof row.value === 'string'
                      ? row.value
                      : JSON.stringify(row.value)
                  }
                />
              </div>
              <button
                aria-label={`Remove input ${i + 1}`}
                className="text-secondary hover:bg-secondary flex size-7 shrink-0 items-center justify-center rounded-md"
                onClick={() => update(rows.filter((_, j) => j !== i))}
                type="button"
              >
                <X className="size-3.5" />
              </button>
            </div>
            {error && <p className="text-danger text-xs">{error}</p>}
          </div>
        )
      })}
      {rows.length < MAX_INPUTS && (
        <button
          className="border-input text-secondary hover:border-amber-border hover:text-primary flex h-8.5 items-center justify-center gap-1.5 rounded-md border border-dashed text-sm"
          onClick={() =>
            update([...rows, { key: crypto.randomUUID(), name: '', value: '' }])
          }
          type="button"
        >
          <Plus className="size-3.5" />
          Add input
        </button>
      )}
    </div>
  )
}

function nameError(name: string, repeated: boolean): null | string {
  if (!name) return null
  if (!NAME.test(name)) {
    return 'Use lowercase letters, digits, and _, starting with a letter.'
  }
  if (KEYWORDS.has(name)) return 'This name is a Python keyword.'
  if (repeated) return 'Another input has this name.'
  return null
}

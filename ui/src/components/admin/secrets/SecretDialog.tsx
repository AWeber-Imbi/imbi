import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { parseObject } from '@/lib/utils'

/**
 * One form field. `list` is comma separated text sent as a string
 * array; `json` is a JSON object; `multi` is a set of checkboxes.
 * A field with a `group` is sent in `body[group]`; a group with only
 * empty fields is sent as null, and its `required` fields are required
 * only when a field of the group has a value. A `createOnly` field is
 * not shown in an edit, because the API does not change it.
 */
export interface FieldSpec {
  createOnly?: boolean
  description?: string
  group?: string
  initial?: string | string[]
  kind: 'json' | 'list' | 'multi' | 'number' | 'select' | 'text'
  label: string
  name: string
  options?: readonly { label: string; value: string }[]
  required?: boolean
  show?: (values: Values) => boolean
}

interface SecretDialogProps {
  description: string
  error?: unknown
  fields: FieldSpec[]
  isPending: boolean
  onClose: () => void
  onSubmit: (values: Record<string, unknown>) => void
  /** The row to edit. The dialog then sends only the changed fields. */
  original?: Record<string, unknown>
  title: string
}

type Values = Record<string, string | string[]>

/** A create or edit dialog for a provider, a binding, or a grant. */
// fallow-ignore-next-line complexity
export function SecretDialog({
  description,
  error,
  fields,
  isPending,
  onClose,
  onSubmit,
  original,
  title,
}: SecretDialogProps) {
  const [values, setValues] = useState<Values>(() =>
    Object.fromEntries(fields.map((f) => [f.name, initialValue(f, original)])),
  )
  const visible = fields.filter(
    (f) => !(original && f.createOnly) && (f.show?.(values) ?? true),
  )
  const [parseError, setParseError] = useState<null | string>(null)
  const set = (name: string, value: string | string[]) =>
    setValues((prev) => ({ ...prev, [name]: value }))

  const submit = () => {
    try {
      const body = toBody(visible, values, original)
      if (original && !Object.keys(body).length) return onClose()
      onSubmit(body)
      setParseError(null)
    } catch (err) {
      setParseError(err instanceof Error ? err.message : String(err))
    }
  }

  // fallow-ignore-next-line complexity
  const renderInput = (field: FieldSpec) => {
    const id = `secret-${field.name}`
    const value = values[field.name]
    if (field.kind === 'select') {
      return (
        <Select
          onValueChange={(next) => set(field.name, next)}
          value={value as string}
        >
          <SelectTrigger aria-label={field.label} id={id}>
            <SelectValue placeholder={`Select ${field.label.toLowerCase()}`} />
          </SelectTrigger>
          <SelectContent>
            {field.options?.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
    }
    if (field.kind === 'multi') {
      const selected = value as string[]
      return (
        <div className="flex flex-wrap gap-4">
          {field.options?.map((option) => (
            <label
              className="text-primary flex items-center gap-2 text-sm"
              key={option.value}
            >
              <Checkbox
                aria-label={option.label}
                checked={selected.includes(option.value)}
                onCheckedChange={(checked) =>
                  set(
                    field.name,
                    checked
                      ? [...selected, option.value]
                      : selected.filter((v) => v !== option.value),
                  )
                }
              />
              {option.label}
            </label>
          ))}
        </div>
      )
    }
    if (field.kind === 'json') {
      return (
        <Textarea
          className="font-mono text-xs"
          id={id}
          onChange={(e) => set(field.name, e.target.value)}
          rows={4}
          value={value as string}
        />
      )
    }
    return (
      <Input
        id={id}
        onChange={(e) => set(field.name, e.target.value)}
        type={field.kind === 'number' ? 'number' : 'text'}
        value={value as string}
      />
    )
  }

  const isRequired = (field: FieldSpec) =>
    !!field.required &&
    (!field.group ||
      visible.some((f) => f.group === field.group && !isEmpty(values[f.name])))
  const missing = visible.some((f) => isRequired(f) && isEmpty(values[f.name]))

  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open>
      <DialogContent className="max-w-150">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-4 overflow-y-auto p-6">
          {(error != null || parseError) && (
            <ErrorBanner
              error={error}
              message={parseError ?? undefined}
              title={`Failed to save: ${title.toLowerCase()}`}
            />
          )}
          {visible.map((field) => (
            <FormField
              description={field.description}
              htmlFor={`secret-${field.name}`}
              key={field.name}
              label={field.label}
              required={isRequired(field)}
            >
              {renderInput(field)}
            </FormField>
          ))}
        </div>
        <DialogFooter>
          <Button onClick={onClose} variant="outline">
            Cancel
          </Button>
          <Button disabled={isPending || missing} onClick={submit}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const isEmpty = (value: string | string[]) =>
  Array.isArray(value) ? !value.length : !value.trim()

// fallow-ignore-next-line complexity
function initialValue(
  field: FieldSpec,
  original?: Record<string, unknown>,
): string | string[] {
  const source = field.group
    ? (original?.[field.group] as null | Record<string, unknown> | undefined)
    : original
  const value = source?.[field.name]
  if (value === undefined || value === null) {
    return field.initial ?? (field.kind === 'multi' ? [] : '')
  }
  if (field.kind === 'multi') return value as string[]
  if (field.kind === 'list') return (value as string[]).join(', ')
  if (field.kind === 'json') return JSON.stringify(value, null, 2)
  return String(value as number | string)
}

/** The request body. In an edit, only the fields that changed. */
// fallow-ignore-next-line complexity
function toBody(
  fields: FieldSpec[],
  values: Values,
  original?: Record<string, unknown>,
): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  for (const field of fields) {
    const value = toValue(field, values[field.name], !!original)
    if (value === undefined) continue
    if (field.group) {
      body[field.group] ??= {}
      ;(body[field.group] as Record<string, unknown>)[field.name] = value
    } else {
      body[field.name] = value
    }
  }
  for (const group of new Set(fields.map((f) => f.group))) {
    if (!group) continue
    const members = fields.filter((f) => f.group === group)
    if (members.every((f) => isEmpty(values[f.name]))) body[group] = null
  }
  if (!original) return body
  return Object.fromEntries(
    Object.entries(body).filter(
      ([key, value]) => canonical(value) !== canonical(original[key] ?? null),
    ),
  )
}

/**
 * JSON with sorted object keys, and without empty-list properties, so that
 * key order and an absent list do not count as a change.
 */
const canonical = (value: unknown): string =>
  JSON.stringify(value, (_key, val: unknown) =>
    val && typeof val === 'object' && !Array.isArray(val)
      ? Object.fromEntries(
          Object.entries(val)
            .filter(([, v]) => !(Array.isArray(v) && !v.length))
            .sort(([a], [b]) => a.localeCompare(b)),
        )
      : val,
  )

/**
 * The value to send for one field, or undefined to omit it. In an edit,
 * an empty list or text is sent, so that the change clears the value.
 */
// fallow-ignore-next-line complexity
function toValue(
  field: FieldSpec,
  value: string | string[],
  editing: boolean,
): unknown {
  if (field.kind === 'multi') return value
  if (typeof value !== 'string') return undefined
  if (value.trim() === '') {
    if (!editing) return undefined
    if (field.kind === 'list') return []
    return field.kind === 'text' ? '' : undefined
  }
  if (field.kind === 'list') {
    return value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
  }
  if (field.kind === 'number') return Number(value)
  if (field.kind === 'json') return parseObject(field.label, value)
  return value.trim()
}

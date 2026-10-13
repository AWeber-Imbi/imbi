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

/**
 * One form field. `list` is comma separated text sent as a string
 * array; `json` is a JSON object; `multi` is a set of checkboxes.
 */
export interface FieldSpec {
  description?: string
  initial?: string | string[]
  kind: 'json' | 'list' | 'multi' | 'number' | 'select' | 'text'
  label: string
  name: string
  options?: readonly { label: string; value: string }[]
  required?: boolean
}

interface SecretDialogProps {
  description: string
  error?: unknown
  fields: FieldSpec[]
  isPending: boolean
  onClose: () => void
  onSubmit: (values: Record<string, unknown>) => void
  title: string
}

/** A create dialog for a provider, a binding, or a grant. */
// fallow-ignore-next-line complexity
export function SecretDialog({
  description,
  error,
  fields,
  isPending,
  onClose,
  onSubmit,
  title,
}: SecretDialogProps) {
  const [values, setValues] = useState<Record<string, string | string[]>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, initialValue(f)])),
  )
  const [parseError, setParseError] = useState<null | string>(null)
  const set = (name: string, value: string | string[]) =>
    setValues((prev) => ({ ...prev, [name]: value }))

  const submit = () => {
    try {
      onSubmit(toBody(fields, values))
      setParseError(null)
    } catch {
      setParseError('A JSON field is not valid JSON')
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

  const missing = fields.some((f) => {
    const value = values[f.name]
    return f.required && (Array.isArray(value) ? !value.length : !value.trim())
  })

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
          {fields.map((field) => (
            <FormField
              description={field.description}
              htmlFor={`secret-${field.name}`}
              key={field.name}
              label={field.label}
              required={field.required}
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

const initialValue = (field: FieldSpec): string | string[] =>
  field.initial ?? (field.kind === 'multi' ? [] : '')

// fallow-ignore-next-line complexity
function toBody(
  fields: FieldSpec[],
  values: Record<string, string | string[]>,
): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  for (const field of fields) {
    const value = values[field.name]
    if (field.kind === 'multi') {
      body[field.name] = value
    } else if (typeof value !== 'string' || value.trim() === '') {
      continue
    } else if (field.kind === 'list') {
      body[field.name] = value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
    } else if (field.kind === 'number') {
      body[field.name] = Number(value)
    } else if (field.kind === 'json') {
      body[field.name] = JSON.parse(value) as unknown
    } else {
      body[field.name] = value.trim()
    }
  }
  return body
}

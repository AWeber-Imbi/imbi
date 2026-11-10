import { type ReactNode, useState } from 'react'

import { toTitleCase } from '@/components/admin/blueprints/blueprint-schema-utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

import { drawable, type DrawableSchema, fieldKind, jsonObject } from './schema'

/** A toggle button made from a hidden checkbox, so a label finds it. */
export function Chip({
  checked,
  disabled,
  label,
  mono,
  onChange,
  title,
}: {
  checked: boolean
  disabled?: boolean
  label: string
  mono?: boolean
  onChange: (checked: boolean) => void
  title?: string
}) {
  return (
    <label
      className={cn(
        'flex h-8 cursor-pointer items-center rounded-full border border-secondary px-3 text-sm has-checked:border-action has-checked:bg-action has-checked:text-action-foreground has-focus-visible:ring-2 has-focus-visible:ring-ring has-disabled:cursor-not-allowed has-disabled:opacity-50',
        mono && 'font-mono text-xs',
      )}
      title={title}
    >
      <input
        checked={checked}
        className="sr-only"
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        type="checkbox"
      />
      {label}
    </label>
  )
}

export function ChipGroup({
  children,
  hint,
  label,
  required = true,
}: {
  children: ReactNode
  hint?: string
  label: string
  required?: boolean
}) {
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium">
        {label} {required && <RequiredAsterisk />}
        {hint && <span className="text-tertiary ml-2 font-normal">{hint}</span>}
      </legend>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </fieldset>
  )
}

export function Field({
  children,
  help,
  htmlFor,
  label,
  optional,
  required,
}: {
  children: ReactNode
  help?: string
  htmlFor?: string
  label: string
  optional?: boolean
  required?: boolean
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <label className="block text-sm font-medium" htmlFor={htmlFor}>
        {label}
        {required && (
          <>
            {' '}
            <RequiredAsterisk />
          </>
        )}
        {optional && (
          <span className="text-secondary font-normal"> (optional)</span>
        )}
      </label>
      {children}
      {help && <p className="text-secondary text-xs">{help}</p>}
    </div>
  )
}

/** The filter on one resolution, with a button that clears it. */
export function ResolutionChip({
  id,
  onClear,
  title,
}: {
  id: string
  onClear: () => void
  title: string
}) {
  return (
    <Button onClick={onClear} size="sm" title={title} variant="outline">
      Resolution <span className="font-mono">{id.slice(0, 8)}</span> ×
    </Button>
  )
}

/**
 * A boxed JSON object, edited as fields when the schema allows it, or
 * as JSON text. `text` is the source of truth, so both modes agree.
 */
// fallow-ignore-next-line complexity
export function SchemaEditor({
  error,
  hint,
  id,
  label,
  onChange,
  schema: rawSchema,
  text,
}: {
  error?: string
  hint: string
  id: string
  label: string
  onChange: (text: string) => void
  schema: unknown
  text: string
}) {
  const [asJson, setAsJson] = useState(false)
  const schema = drawable(rawSchema)
  const parsed = jsonObject(text)
  // Fields need a schema and a JSON object; else edit the JSON.
  const showFields = !!schema && !!parsed && !asJson
  const keys =
    schema &&
    `Keys: ${Object.keys(schema.properties)
      .map((k) => (schema.required?.includes(k) ? `${k} (required)` : k))
      .join(', ')}.`
  return (
    <fieldset className="border-tertiary overflow-hidden rounded-lg border">
      <legend className="sr-only">{label}</legend>
      <div className="border-tertiary bg-tertiary flex items-center justify-between gap-3 border-b px-3.5 py-2.5">
        <label
          className="text-sm font-medium"
          htmlFor={showFields ? undefined : id}
        >
          {label} <RequiredAsterisk />{' '}
          <span className="text-secondary font-normal">{hint}</span>
        </label>
        {schema && (
          <button
            className="text-info shrink-0 text-xs hover:underline disabled:opacity-50"
            disabled={!asJson && !parsed}
            onClick={() => setAsJson(!asJson)}
            type="button"
          >
            {showFields ? 'Edit as JSON' : 'Edit as fields'}
          </button>
        )}
      </div>
      <div className="space-y-2 p-3.5">
        {showFields ? (
          <SchemaFields
            idPrefix={id}
            onChange={(next) => onChange(JSON.stringify(next, null, 2))}
            schema={schema}
            value={parsed}
          />
        ) : (
          <Textarea
            aria-invalid={!!error}
            className="font-mono text-xs"
            id={id}
            onChange={(e) => onChange(e.target.value)}
            rows={5}
            value={text}
          />
        )}
        {error && <p className="text-destructive text-xs">{error}</p>}
        {!showFields && keys && (
          <p className="text-secondary text-xs">{keys}</p>
        )}
      </div>
    </fieldset>
  )
}

/** Values as removable tags. Enter or a comma adds the typed value. */
export function TagInput({
  id,
  onChange,
  placeholder,
  values,
}: {
  id: string
  onChange: (values: string[]) => void
  placeholder: string
  values: string[]
}) {
  const [text, setText] = useState('')
  const add = () => {
    const value = text.trim()
    if (value && !values.includes(value)) onChange([...values, value])
    setText('')
  }
  return (
    <div className="border-input flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border px-1.5 py-1">
      {values.map((v) => (
        <span
          className="bg-secondary flex h-6 items-center gap-1 rounded pr-1 pl-2 font-mono text-xs"
          key={v}
        >
          {v}
          <button
            aria-label={`Remove ${v}`}
            className="text-secondary hover:text-primary"
            onClick={() => onChange(values.filter((x) => x !== v))}
            type="button"
          >
            ×
          </button>
        </span>
      ))}
      <input
        className="h-6 min-w-40 flex-1 bg-transparent px-1 font-mono text-xs outline-none"
        id={id}
        onBlur={add}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault()
            add()
          } else if (e.key === 'Backspace' && !text && values.length) {
            onChange(values.slice(0, -1))
          }
        }}
        placeholder={placeholder}
        value={text}
      />
    </div>
  )
}

/**
 * Inputs for each field of a schema: text, or tags for a list of text.
 * An empty value removes the key, so optional fields stay absent.
 */
function SchemaFields({
  idPrefix,
  onChange,
  schema,
  value,
}: {
  idPrefix: string
  onChange: (value: Record<string, unknown>) => void
  schema: DrawableSchema
  value: Record<string, unknown>
}) {
  const setKey = (key: string, next: string | string[]) => {
    const copy = { ...value }
    if (next.length) copy[key] = next
    else delete copy[key]
    onChange(copy)
  }
  return (
    <div className="grid grid-cols-2 gap-4">
      {Object.entries(schema.properties).map(([key, field]) => {
        const id = `${idPrefix}-${key}`
        const current = value[key]
        const props = {
          help: field.description,
          htmlFor: id,
          label: field.title ?? toTitleCase(key),
          required: schema.required?.includes(key),
        }
        return fieldKind(field) === 'list' ? (
          <div className="col-span-2" key={key}>
            <Field {...props}>
              <TagInput
                id={id}
                onChange={(v) => setKey(key, v)}
                placeholder="Add a value, press Enter"
                values={Array.isArray(current) ? current.map(String) : []}
              />
            </Field>
          </div>
        ) : (
          <Field key={key} {...props}>
            <Input
              className="font-mono"
              id={id}
              onChange={(e) => setKey(key, e.target.value)}
              placeholder={
                typeof field.default === 'string' ? field.default : undefined
              }
              value={typeof current === 'string' ? current : ''}
            />
          </Field>
        )
      })}
    </div>
  )
}

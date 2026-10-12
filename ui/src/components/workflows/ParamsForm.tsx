import { useState } from 'react'

import { Plus, X } from 'lucide-react'

import { Combobox } from '@/components/ui/combobox'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

import type { FieldSource, ParamField } from './schemaFields'
import { useSourceOptions } from './workflowQueries'

interface ParamsFormProps {
  fields: ParamField[]
  idPrefix: string
  onChange: (name: string, value: unknown) => void
  /** Removes item `index` of a list field (branches also drop their edges). */
  onRemoveItem: (name: string, index: number) => void
  orgSlug: string
  params: Record<string, unknown>
}

/** The inspector form for a node's `params`, built from its type's schema. */
export function ParamsForm({
  fields,
  idPrefix,
  onChange,
  onRemoveItem,
  orgSlug,
  params,
}: ParamsFormProps) {
  return (
    <>
      {fields.map((field) => {
        const id = `${idPrefix}-${field.name}`
        const value = params[field.name]
        return (
          <FormField
            description={field.description}
            htmlFor={id}
            key={field.name}
            label={field.label}
            required={field.required}
          >
            <FieldControl
              field={field}
              id={id}
              onChange={(v) => onChange(field.name, v)}
              onRemoveItem={(i) => onRemoveItem(field.name, i)}
              orgSlug={orgSlug}
              value={value}
            />
          </FormField>
        )
      })}
    </>
  )
}

export function SelectField({
  id,
  onChange,
  options,
  value,
}: {
  id: string
  onChange: (value: string) => void
  options: { label: string; value: string }[]
  value: string
}) {
  return (
    <Select onValueChange={onChange} value={value}>
      <SelectTrigger id={id}>
        <SelectValue placeholder="Choose…" />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function FieldControl({
  field,
  id,
  onChange,
  onRemoveItem,
  orgSlug,
  value,
}: {
  field: ParamField
  id: string
  onChange: (value: unknown) => void
  onRemoveItem: (index: number) => void
  orgSlug: string
  value: unknown
}) {
  switch (field.kind) {
    case 'boolean':
      return (
        <Switch
          checked={value === true}
          id={id}
          onCheckedChange={(checked) => onChange(checked)}
        />
      )
    case 'json':
      return <JsonField id={id} onChange={onChange} value={value} />
    case 'list':
      return (
        <ListField
          id={id}
          onChange={onChange}
          onRemove={onRemoveItem}
          value={Array.isArray(value) ? value.map(String) : []}
        />
      )
    case 'multiline':
      return (
        <Textarea
          className={cn(field.mono && 'font-mono text-xs')}
          id={id}
          onChange={(e) => onChange(e.target.value)}
          rows={4}
          value={typeof value === 'string' ? value : ''}
        />
      )
    case 'number':
      return (
        <Input
          id={id}
          onChange={(e) =>
            onChange(e.target.value === '' ? undefined : Number(e.target.value))
          }
          type="number"
          value={typeof value === 'number' ? value : ''}
        />
      )
    case 'select':
      return (
        <SelectField
          id={id}
          onChange={onChange}
          options={field.options.map((o) => ({ label: o, value: o }))}
          value={typeof value === 'string' ? value : ''}
        />
      )
    case 'source':
      return (
        <SourceField
          id={id}
          onChange={onChange}
          orgSlug={orgSlug}
          source={field.source}
          value={typeof value === 'string' ? value : ''}
        />
      )
    case 'text':
      return (
        <Input
          id={id}
          onChange={(e) => onChange(e.target.value)}
          value={typeof value === 'string' ? value : ''}
        />
      )
  }
}

/** Any value the form has no control for, edited as JSON. */
function JsonField({
  id,
  onChange,
  value,
}: {
  id: string
  onChange: (value: unknown) => void
  value: unknown
}) {
  const [text, setText] = useState(() =>
    value === undefined ? '' : JSON.stringify(value, null, 2),
  )
  const [invalid, setInvalid] = useState(false)
  return (
    <>
      <Textarea
        aria-invalid={invalid}
        className="font-mono text-xs"
        id={id}
        onChange={(e) => {
          setText(e.target.value)
          if (e.target.value.trim() === '') {
            setInvalid(false)
            onChange(undefined)
            return
          }
          try {
            onChange(JSON.parse(e.target.value))
            setInvalid(false)
          } catch {
            setInvalid(true)
          }
        }}
        rows={4}
        value={text}
      />
      {invalid && <p className="text-danger mt-1 text-xs">Not valid JSON.</p>}
    </>
  )
}

function ListField({
  id,
  onChange,
  onRemove,
  value,
}: {
  id: string
  onChange: (value: string[]) => void
  onRemove: (index: number) => void
  value: string[]
}) {
  return (
    <div className="flex flex-col gap-2" id={id}>
      {value.map((item, i) => (
        <div className="flex items-center gap-1.5" key={i}>
          <span className="text-tertiary w-5.5 text-center font-mono text-xs">
            {i + 1}
          </span>
          <Input
            aria-label={`Item ${i + 1}`}
            className="h-8.5"
            onChange={(e) =>
              onChange(value.map((v, j) => (j === i ? e.target.value : v)))
            }
            value={item}
          />
          <button
            aria-label={`Remove item ${i + 1}`}
            className="text-secondary hover:bg-secondary flex size-7 shrink-0 items-center justify-center rounded-md"
            onClick={() => onRemove(i)}
            type="button"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
      <button
        className="border-input text-secondary hover:border-amber-border hover:text-primary flex h-8.5 items-center justify-center gap-1.5 rounded-md border border-dashed text-sm"
        onClick={() => onChange([...value, `Option ${value.length + 1}`])}
        type="button"
      >
        <Plus className="size-3.5" />
        Add
      </button>
    </div>
  )
}

function SourceField({
  id,
  onChange,
  orgSlug,
  source,
  value,
}: {
  id: string
  onChange: (value: string) => void
  orgSlug: string
  source: FieldSource
  value: string
}) {
  const { loading, options } = useSourceOptions(orgSlug, source)
  return (
    <Combobox
      id={id}
      onChange={onChange}
      options={options}
      placeholder={loading ? 'Loading…' : 'Choose…'}
      value={value}
    />
  )
}

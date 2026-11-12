import { Plus, X } from 'lucide-react'

import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import {
  blankField,
  FIELD_TYPES,
  hasSubFields,
  isStringValued,
  ITEM_TYPES,
  MAX_OPTIONAL_FIELDS,
  nameError,
  normalize,
  optionalCount,
  type OutputField,
  SCALAR_TYPES,
  STRING_FORMATS,
} from './outputFields'
import { SelectField } from './ParamsForm'

const MAX_FIELDS = 50
const ANY_TEXT = 'any'
const ONE_OF = 'enum'

const FORMAT_LABELS: Record<(typeof STRING_FORMATS)[number], string> = {
  date: 'A date',
  'date-time': 'A date and time',
  duration: 'A duration',
  email: 'An email address',
  hostname: 'A hostname',
  ipv4: 'An IPv4 address',
  ipv6: 'An IPv6 address',
  time: 'A time',
  uri: 'A URL',
  uuid: 'A UUID',
}

const VALUE_RULES = [
  { label: 'Any text', value: ANY_TEXT },
  { label: 'One of a list of values', value: ONE_OF },
  ...STRING_FORMATS.map((format) => ({
    label: FORMAT_LABELS[format],
    value: format,
  })),
]

export function OutputFieldsField({
  id,
  label,
  onChange,
  value,
}: {
  id: string
  label: string
  onChange: (value: OutputField[]) => void
  value: OutputField[]
}) {
  const optional = optionalCount(value)
  return (
    <div
      aria-label={label}
      className="flex flex-col gap-2"
      id={id}
      role="group"
    >
      <FieldList fields={value} id={id} label="Field " onChange={onChange} />
      {optional > 0 && (
        <p
          className={cn(
            'text-xs',
            optional > MAX_OPTIONAL_FIELDS ? 'text-danger' : 'text-tertiary',
          )}
        >
          {optional} of {MAX_OPTIONAL_FIELDS} optional fields.
        </p>
      )}
    </div>
  )
}

/** The allowed values of a string field, one per row. */
function EnumList({
  label,
  onChange,
  values,
}: {
  label: string
  onChange: (values: string[]) => void
  values: string[]
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {values.map((value, index) => (
        <div className="flex items-center gap-1.5" key={index}>
          <Input
            aria-label={`${label} ${index + 1}`}
            className="text-xs"
            onChange={(event) =>
              onChange(
                values.map((other, position) =>
                  position === index ? event.target.value : other,
                ),
              )
            }
            placeholder="Value"
            value={value}
          />
          <button
            aria-label={`Remove ${label.toLowerCase()} ${index + 1}`}
            className="text-secondary hover:bg-secondary flex size-7 shrink-0 items-center justify-center rounded-md"
            onClick={() =>
              onChange(values.filter((_, position) => position !== index))
            }
            type="button"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
      <button
        className="text-secondary hover:text-primary flex items-center gap-1.5 self-start text-xs"
        onClick={() => onChange([...values, ''])}
        type="button"
      >
        <Plus className="size-3" />
        Add value
      </button>
    </div>
  )
}

function FieldList({
  fields,
  id,
  label,
  nested = false,
  onChange,
}: {
  fields: OutputField[]
  id: string
  label: string
  nested?: boolean
  onChange: (fields: OutputField[]) => void
}) {
  return (
    <>
      {fields.map((field, index) => (
        <FieldRow
          field={field}
          id={`${id}-${index}`}
          key={index}
          label={`${label}${index + 1}`}
          nested={nested}
          onChange={(next) =>
            onChange(
              fields.map((other, position) =>
                position === index ? next : other,
              ),
            )
          }
          onRemove={() =>
            onChange(fields.filter((_, position) => position !== index))
          }
          siblings={fields}
        />
      ))}
      {fields.length < MAX_FIELDS && (
        <button
          className="border-input text-secondary hover:border-amber-border hover:text-primary flex h-8.5 items-center justify-center gap-1.5 rounded-md border border-dashed text-sm"
          onClick={() => onChange([...fields, blankField(fields)])}
          type="button"
        >
          <Plus className="size-3.5" />
          {nested ? 'Add sub-field' : 'Add field'}
        </button>
      )}
    </>
  )
}

function FieldRow({
  field,
  id,
  label,
  nested,
  onChange,
  onRemove,
  siblings,
}: {
  field: OutputField
  id: string
  label: string
  nested: boolean
  onChange: (field: OutputField) => void
  onRemove: () => void
  siblings: OutputField[]
}) {
  const set = (patch: Partial<OutputField>) =>
    onChange(normalize({ ...field, ...patch }))
  const error = nameError(field, siblings)
  return (
    <div className="border-tertiary flex flex-col gap-2 rounded-md border p-2">
      <div className="flex items-center gap-1.5">
        <Input
          aria-invalid={error !== undefined}
          aria-label={`${label} name`}
          className="font-mono text-xs"
          onChange={(event) => set({ name: event.target.value })}
          value={field.name}
        />
        <div className="w-28 shrink-0">
          <SelectField
            id={`${id}-type`}
            label={`${label} type`}
            onChange={(type) => set({ type: type as OutputField['type'] })}
            options={options(nested ? SCALAR_TYPES : FIELD_TYPES)}
            value={field.type}
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
      {error && <p className="text-danger text-xs">{error}</p>}
      {field.type === 'array' && (
        <SelectField
          id={`${id}-items`}
          label={`${label} items`}
          onChange={(items) => set({ items: items as OutputField['items'] })}
          options={ITEM_TYPES.map((type) => ({
            label: `Each item: ${type}`,
            value: type,
          }))}
          value={field.items ?? 'string'}
        />
      )}
      <Input
        aria-label={`${label} description`}
        className="text-xs"
        onChange={(event) => set({ description: event.target.value })}
        placeholder="Description for the agent"
        value={field.description ?? ''}
      />
      {isStringValued(field) && (
        <SelectField
          id={`${id}-values`}
          label={`${label} values`}
          onChange={(rule) => set(valueRule(rule))}
          options={VALUE_RULES}
          value={valueRuleOf(field)}
        />
      )}
      {isStringValued(field) && field.enum?.length ? (
        <EnumList
          label={`${label} allowed value`}
          onChange={(values) => set({ enum: values })}
          values={field.enum}
        />
      ) : null}
      <label className="flex items-center gap-2 text-xs">
        <Checkbox
          aria-label={`${label} required`}
          checked={field.required !== false}
          onCheckedChange={(checked) => set({ required: checked === true })}
        />
        Required
      </label>
      {!nested && hasSubFields(field) && (
        <div className="border-tertiary flex flex-col gap-2 border-l-2 pl-2">
          <span className="text-tertiary text-xs">
            {field.type === 'array' ? 'Fields of each object' : 'Fields'}
          </span>
          <FieldList
            fields={field.fields ?? []}
            id={`${id}-fields`}
            label={`${label}.`}
            nested
            onChange={(fields) => set({ fields })}
          />
        </div>
      )}
    </div>
  )
}

function options(
  values: readonly string[],
): { label: string; value: string }[] {
  return values.map((value) => ({ label: value, value }))
}

function valueRule(rule: string): Partial<OutputField> {
  if (rule === ONE_OF) return { enum: [''], format: null }
  if (rule === ANY_TEXT) return { enum: null, format: null }
  return { enum: null, format: rule as OutputField['format'] }
}

function valueRuleOf(field: OutputField): string {
  if (field.enum?.length) return ONE_OF
  return field.format ?? ANY_TEXT
}

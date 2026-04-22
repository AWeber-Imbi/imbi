/* eslint-disable react-refresh/only-export-components */
import Ajv from 'ajv'
import addFormats from 'ajv-formats'
import { AlertCircle } from 'lucide-react'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { DynamicFieldSchema, DynamicSchema } from '@/api/endpoints'

// Radix SelectItem rejects empty-string values, so use a sentinel to represent
// an unset non-required enum field (preserves the clear-via-placeholder
// behaviour of the native <select> this component replaced).
const UNSET_VALUE = '__unset__'

const ajv = new Ajv({ allErrors: true })
addFormats(ajv)

function toTitleCase(key: string): string {
  return key
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function getInputType(field: DynamicFieldSchema): string {
  if (field.format === 'email') return 'email'
  if (field.format === 'uri' || field.format === 'url') return 'url'
  if (field.type === 'integer' || field.type === 'number') return 'number'
  return 'text'
}

export function validateDynamicFields(
  schema: DynamicSchema,
  data: Record<string, unknown>,
): Record<string, string> {
  const jsonSchema = {
    type: 'object' as const,
    properties: schema.properties,
    ...(schema.required?.length ? { required: schema.required } : {}),
  }
  const validate = ajv.compile(jsonSchema)
  validate(data)
  const fieldErrors: Record<string, string> = {}
  if (validate.errors) {
    for (const err of validate.errors) {
      const field =
        err.instancePath?.replace(/^\//, '') ||
        ((err.params as Record<string, unknown>)?.missingProperty as string)
      if (field) {
        fieldErrors[field] = err.message || 'Invalid value'
      }
    }
  }
  return fieldErrors
}

// --- Form mode: editable fields ---

interface DynamicFormFieldsProps {
  schema: DynamicSchema
  data: Record<string, unknown>
  errors: Record<string, string>
  onChange: (key: string, value: unknown) => void
  isLoading?: boolean
}

export function DynamicFormFields({
  schema,
  data,
  errors,
  onChange,
  isLoading = false,
}: DynamicFormFieldsProps) {
  const fields = Object.entries(schema.properties)
  if (fields.length === 0) return null

  return (
    <>
      {fields.map(([key, field]) => {
        const label = field.title || toTitleCase(key)
        const isRequired = schema.required?.includes(key) ?? false
        const fieldError = errors[key]
        const value = (data[key] as string) ?? ''

        if (field.enum) {
          return (
            <div key={key}>
              <label className="mb-1.5 block text-sm text-secondary">
                {label}
                {isRequired && <span className="text-red-500"> *</span>}
              </label>
              <Select
                value={value || (!isRequired ? UNSET_VALUE : '')}
                onValueChange={(v) =>
                  onChange(key, v === UNSET_VALUE ? undefined : v)
                }
                disabled={isLoading}
              >
                <SelectTrigger className={fieldError ? 'border-red-500' : ''}>
                  <SelectValue
                    placeholder={`Select ${label.toLowerCase()}...`}
                  />
                </SelectTrigger>
                <SelectContent>
                  {!isRequired && (
                    <SelectItem value={UNSET_VALUE}>None</SelectItem>
                  )}
                  {field.enum.map((opt) => (
                    <SelectItem key={opt} value={opt}>
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {field.description && (
                <p className="mt-1 text-xs text-tertiary">
                  {field.description}
                </p>
              )}
              {fieldError && (
                <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                  <AlertCircle className="h-3 w-3" />
                  {fieldError}
                </div>
              )}
            </div>
          )
        }

        if (field.type === 'boolean') {
          return (
            <div key={key} className="flex items-center gap-2">
              <input
                type="checkbox"
                id={`dynamic-${key}`}
                checked={!!data[key]}
                onChange={(e) => onChange(key, e.target.checked)}
                disabled={isLoading}
                className="rounded border-gray-300"
              />
              <label
                htmlFor={`dynamic-${key}`}
                className="text-sm text-secondary"
              >
                {label}
              </label>
              {field.description && (
                <span className="text-xs text-tertiary">
                  — {field.description}
                </span>
              )}
            </div>
          )
        }

        return (
          <div key={key}>
            <label className="mb-1.5 block text-sm text-secondary">
              {label}
              {isRequired && <span className="text-red-500"> *</span>}
            </label>
            <Input
              type={getInputType(field)}
              value={value}
              onChange={(e) => {
                const raw = e.target.value
                if (raw === '') return onChange(key, undefined)
                if (field.type === 'integer')
                  return onChange(key, Number.parseInt(raw, 10))
                if (field.type === 'number')
                  return onChange(key, Number.parseFloat(raw))
                return onChange(key, raw)
              }}
              disabled={isLoading}
              min={field.minimum}
              max={field.maximum}
              minLength={field.minLength}
              maxLength={field.maxLength}
              className={` ${fieldError ? 'border-red-500' : ''}`}
            />
            {field.description && (
              <p className="mt-1 text-xs text-tertiary">{field.description}</p>
            )}
            {fieldError && (
              <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                <AlertCircle className="h-3 w-3" />
                {fieldError}
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}

// --- Detail mode: read-only display ---

interface DynamicDetailFieldsProps {
  schema: DynamicSchema
  data: Record<string, unknown>
}

export function DynamicDetailFields({
  schema,
  data,
}: DynamicDetailFieldsProps) {
  const fields = Object.entries(schema.properties)
  if (fields.length === 0) return null

  return (
    <>
      {fields.map(([key, field]) => {
        const label = field.title || toTitleCase(key)
        const value = data[key]
        if (value === undefined || value === null || value === '') return null

        return (
          <div key={key}>
            <div className="text-sm text-secondary">{label}</div>
            <div className="mt-1 text-primary">
              {typeof value === 'boolean'
                ? value
                  ? 'Yes'
                  : 'No'
                : String(value)}
            </div>
          </div>
        )
      })}
    </>
  )
}

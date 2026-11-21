/* eslint-disable react-refresh/only-export-components */
import Ajv from 'ajv'
import addFormats from 'ajv-formats'
import { AlertCircle } from 'lucide-react'

import type {
  DynamicFieldSchema,
  DynamicSchema,
  ProjectSchemaSection,
  ProjectSchemaSectionProperty,
} from '@/api/endpoints'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// Radix SelectItem rejects empty-string values, so use a sentinel to represent
// an unset non-required enum field (preserves the clear-via-placeholder
// behaviour of the native <select> this component replaced).
const UNSET_VALUE = '__unset__'

const ajv = new Ajv({ allErrors: true })
addFormats(ajv)

interface DynamicDetailFieldsProps {
  data: Record<string, unknown>
  schema: DynamicSchema
}

interface DynamicFormFieldsProps {
  data: Record<string, unknown>
  errors: Record<string, string>
  isLoading?: boolean
  onChange: (key: string, value: unknown) => void
  schema: DynamicSchema
}

export function DynamicDetailFields({
  data,
  schema,
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
            <div className="text-secondary text-sm">{label}</div>
            <div className="text-primary mt-1">
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

// --- Form mode: editable fields ---

export function DynamicFormFields({
  data,
  errors,
  isLoading = false,
  onChange,
  schema,
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
              <Label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor={`dynamic-${key}`}
              >
                {label}
                {isRequired && <span className="text-red-500"> *</span>}
              </Label>
              <Select
                disabled={isLoading}
                onValueChange={(v) =>
                  onChange(key, v === UNSET_VALUE ? undefined : v)
                }
                value={value || (!isRequired ? UNSET_VALUE : '')}
              >
                <SelectTrigger
                  className={fieldError ? 'border-red-500' : ''}
                  id={`dynamic-${key}`}
                >
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
                <p className="text-tertiary mt-1 text-xs">
                  {field.description}
                </p>
              )}
              {fieldError && (
                <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                  <AlertCircle className="size-3" />
                  {fieldError}
                </div>
              )}
            </div>
          )
        }

        // An array or an object is JSON text. Text that does not parse
        // stays a string, so the check shows an error for it.
        if (field.type === 'array' || field.type === 'object') {
          const raw = data[key]
          return (
            <div key={key}>
              <Label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor={`dynamic-${key}`}
              >
                {label}
                {isRequired && <span className="text-red-500"> *</span>}
              </Label>
              <Input
                className={`font-mono ${fieldError ? 'border-red-500' : ''}`}
                disabled={isLoading}
                id={`dynamic-${key}`}
                onChange={(e) => {
                  const text = e.target.value
                  if (text === '') return onChange(key, undefined)
                  try {
                    onChange(key, JSON.parse(text))
                  } catch {
                    onChange(key, text)
                  }
                }}
                placeholder={field.type === 'array' ? '["a", "b"]' : '{"a": 1}'}
                value={
                  raw === undefined || typeof raw === 'string'
                    ? (raw ?? '')
                    : JSON.stringify(raw)
                }
              />
              {field.description && (
                <p className="text-tertiary mt-1 text-xs">
                  {field.description}
                </p>
              )}
              {fieldError && (
                <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                  <AlertCircle className="size-3" />
                  {fieldError}
                </div>
              )}
            </div>
          )
        }

        if (field.type === 'boolean') {
          return (
            <div className="flex items-center gap-2" key={key}>
              <Checkbox
                aria-describedby={
                  fieldError ? `dynamic-${key}-error` : undefined
                }
                aria-invalid={fieldError ? true : undefined}
                checked={!!data[key]}
                disabled={isLoading}
                id={`dynamic-${key}`}
                onCheckedChange={(checked) => onChange(key, checked === true)}
              />
              <Label
                className="text-secondary text-sm"
                htmlFor={`dynamic-${key}`}
              >
                {label}
              </Label>
              {field.description && (
                <span className="text-tertiary text-xs">
                  — {field.description}
                </span>
              )}
              {fieldError && (
                <span
                  className="text-danger flex items-center gap-1 text-xs"
                  id={`dynamic-${key}-error`}
                >
                  <AlertCircle className="size-3" />
                  {fieldError}
                </span>
              )}
            </div>
          )
        }

        return (
          <div key={key}>
            <Label
              className="text-secondary mb-1.5 block text-sm"
              htmlFor={`dynamic-${key}`}
            >
              {label}
              {isRequired && <span className="text-red-500"> *</span>}
            </Label>
            <Input
              className={` ${fieldError ? 'border-red-500' : ''}`}
              disabled={isLoading}
              id={`dynamic-${key}`}
              max={field.maximum}
              maxLength={field.maxLength}
              min={field.minimum}
              minLength={field.minLength}
              onChange={(e) => {
                const raw = e.target.value
                if (raw === '') return onChange(key, undefined)
                if (field.type === 'integer')
                  return onChange(key, Number.parseInt(raw, 10))
                if (field.type === 'number')
                  return onChange(key, Number.parseFloat(raw))
                return onChange(key, raw)
              }}
              type={getInputType(field)}
              value={value}
            />
            {field.description && (
              <p className="text-tertiary mt-1 text-xs">{field.description}</p>
            )}
            {fieldError && (
              <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                <AlertCircle className="size-3" />
                {fieldError}
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}

// A create fails when a matching blueprint has a required field with no
// default, so collect only those fields here. A later blueprint overrides
// an earlier one for the same field, as the API does when it builds the
// model.
export function requiredBlueprintFields(
  sections: ProjectSchemaSection[] | undefined,
): DynamicSchema {
  const properties: Record<string, DynamicFieldSchema> = {}
  for (const section of sections ?? []) {
    if (section.scope === 'environment') continue
    for (const [key, prop] of Object.entries(section.properties)) {
      if (!section.required?.includes(key) || prop.default != null) {
        delete properties[key]
        continue
      }
      properties[key] = toDynamicField(prop)
    }
  }
  return { properties, required: Object.keys(properties) }
}

/** A blueprint section property as a form field, without its nulls. */
export function toDynamicField(
  prop: Omit<ProjectSchemaSectionProperty, 'x-display' | 'x-ui'>,
): DynamicFieldSchema {
  return {
    description: prop.description ?? undefined,
    enum: prop.enum ?? undefined,
    format: prop.format ?? undefined,
    items: prop.items
      ? {
          enum: prop.items.enum ?? undefined,
          type: prop.items.type ?? undefined,
        }
      : undefined,
    maximum: prop.maximum ?? undefined,
    minimum: prop.minimum ?? undefined,
    title: prop.title ?? undefined,
    type: prop.type ?? undefined,
  }
}

export function validateDynamicFields(
  schema: DynamicSchema,
  data: Record<string, unknown>,
): Record<string, string> {
  const jsonSchema = {
    properties: schema.properties,
    type: 'object' as const,
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

// --- Detail mode: read-only display ---

function getInputType(field: DynamicFieldSchema): string {
  if (field.format === 'email') return 'email'
  if (field.format === 'uri' || field.format === 'url') return 'url'
  if (field.type === 'integer' || field.type === 'number') return 'number'
  return 'text'
}

function toTitleCase(key: string): string {
  return key
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

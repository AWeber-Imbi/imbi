import Ajv from 'ajv'
import addFormats from 'ajv-formats'
import { AlertCircle } from 'lucide-react'
import { Input } from './input'
import type { DynamicFieldSchema, DynamicSchema } from '@/api/endpoints'

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
  data: Record<string, unknown>
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
      const field = err.instancePath?.replace(/^\//, '') ||
        (err.params as Record<string, unknown>)?.missingProperty as string
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
  isDarkMode: boolean
  isLoading?: boolean
}

export function DynamicFormFields({
  schema,
  data,
  errors,
  onChange,
  isDarkMode,
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
              <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                {label}{isRequired && <span className="text-red-500"> *</span>}
              </label>
              <select
                value={value}
                onChange={(e) => onChange(key, e.target.value || undefined)}
                disabled={isLoading}
                className={`w-full px-3 py-2 rounded-lg border text-sm ${
                  isDarkMode
                    ? 'bg-gray-700 border-gray-600 text-white'
                    : 'bg-white border-gray-300 text-gray-900'
                } ${fieldError ? 'border-red-500' : ''}`}
              >
                <option value="">Select {label.toLowerCase()}...</option>
                {field.enum.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              {field.description && (
                <p className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                  {field.description}
                </p>
              )}
              {fieldError && (
                <div className={`flex items-center gap-1 mt-1 text-xs ${
                  isDarkMode ? 'text-red-400' : 'text-red-600'
                }`}>
                  <AlertCircle className="w-3 h-3" />
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
                className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                {label}
              </label>
              {field.description && (
                <span className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                  — {field.description}
                </span>
              )}
            </div>
          )
        }

        return (
          <div key={key}>
            <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
              {label}{isRequired && <span className="text-red-500"> *</span>}
            </label>
            <Input
              type={getInputType(field)}
              value={value}
              onChange={(e) => onChange(key, e.target.value || undefined)}
              disabled={isLoading}
              min={field.minimum}
              max={field.maximum}
              minLength={field.minLength}
              maxLength={field.maxLength}
              className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                fieldError ? 'border-red-500' : ''
              }`}
            />
            {field.description && (
              <p className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                {field.description}
              </p>
            )}
            {fieldError && (
              <div className={`flex items-center gap-1 mt-1 text-xs ${
                isDarkMode ? 'text-red-400' : 'text-red-600'
              }`}>
                <AlertCircle className="w-3 h-3" />
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
  isDarkMode: boolean
}

export function DynamicDetailFields({
  schema,
  data,
  isDarkMode,
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
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              {label}
            </div>
            <div className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
              {typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}
            </div>
          </div>
        )
      })}
    </>
  )
}

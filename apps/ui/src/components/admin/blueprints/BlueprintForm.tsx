import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Save, X, AlertCircle, AlertTriangle, Plus, Trash2,
  ChevronUp, ChevronDown, Code, List
} from 'lucide-react'
import Ajv from 'ajv'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { getBlueprint } from '@/api/endpoints'
import type { Blueprint, BlueprintCreate, SchemaProperty } from '@/types'

const ajv = new Ajv()

interface BlueprintFormProps {
  blueprintKey: { type: string; slug: string } | null
  blueprintTypes: string[]
  onSave: (data: BlueprintCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  error?: any
  checkPriorityConflict: (
    type: string,
    priority: number,
    excludeSlug?: string
  ) => Blueprint[]
}

type SchemaEditorMode = 'visual' | 'code'

const PROPERTY_TYPES: SchemaProperty['type'][] = [
  'string', 'integer', 'number', 'boolean', 'array', 'object',
]

const STRING_FORMATS = [
  '', 'date', 'date-time', 'email', 'uri', 'uri-reference', 'hostname',
  'ipv4', 'ipv6', 'uuid',
]

function toSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

function generateId(): string {
  return Math.random().toString(36).substring(2, 9)
}

function buildJsonSchema(properties: SchemaProperty[]): Record<string, unknown> {
  const schema: Record<string, unknown> = {
    type: 'object',
    properties: {} as Record<string, unknown>,
  }
  const required: string[] = []
  const props = schema.properties as Record<string, Record<string, unknown>>

  for (const prop of properties) {
    const propSchema: Record<string, unknown> = { type: prop.type }

    if (prop.description) propSchema.description = prop.description
    if (prop.format) propSchema.format = prop.format
    if (prop.defaultValue !== undefined && prop.defaultValue !== '') {
      if (prop.type === 'integer' || prop.type === 'number') {
        propSchema.default = Number(prop.defaultValue)
      } else if (prop.type === 'boolean') {
        propSchema.default = prop.defaultValue === 'true'
      } else {
        propSchema.default = prop.defaultValue
      }
    }
    if (prop.enumValues && prop.enumValues.length > 0) {
      propSchema.enum = prop.enumValues
    }
    if (prop.minimum !== undefined) propSchema.minimum = prop.minimum
    if (prop.maximum !== undefined) propSchema.maximum = prop.maximum
    if (prop.minLength !== undefined) propSchema.minLength = prop.minLength
    if (prop.maxLength !== undefined) propSchema.maxLength = prop.maxLength

    if (prop.type === 'array') {
      propSchema.items = { type: 'string' }
    }

    props[prop.name] = propSchema
    if (prop.required) required.push(prop.name)
  }

  if (required.length > 0) schema.required = required
  return schema
}

function schemaToProperties(
  schema: Record<string, unknown>
): SchemaProperty[] {
  const props = (schema.properties || {}) as Record<
    string,
    Record<string, unknown>
  >
  const required = (schema.required || []) as string[]
  const result: SchemaProperty[] = []

  for (const [name, propSchema] of Object.entries(props)) {
    result.push({
      id: generateId(),
      name,
      type: (propSchema.type as SchemaProperty['type']) || 'string',
      format: propSchema.format as string | undefined,
      description: propSchema.description as string | undefined,
      required: required.includes(name),
      defaultValue:
        propSchema.default !== undefined
          ? String(propSchema.default)
          : undefined,
      enumValues: propSchema.enum as string[] | undefined,
      minimum: propSchema.minimum as number | undefined,
      maximum: propSchema.maximum as number | undefined,
      minLength: propSchema.minLength as number | undefined,
      maxLength: propSchema.maxLength as number | undefined,
    })
  }

  return result
}

export function BlueprintForm({
  blueprintKey,
  blueprintTypes,
  onSave,
  onCancel,
  isDarkMode,
  isLoading = false,
  error,
  checkPriorityConflict,
}: BlueprintFormProps) {
  const isEditing = !!blueprintKey

  // Fetch existing blueprint when editing
  const {
    data: existingBlueprint,
    isLoading: bpLoading,
    error: bpError,
  } = useQuery({
    queryKey: ['blueprint', blueprintKey?.type, blueprintKey?.slug],
    queryFn: () => getBlueprint(blueprintKey!.type, blueprintKey!.slug),
    enabled: isEditing,
  })

  // Form state
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [type, setType] = useState('')
  const [description, setDescription] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [priority, setPriority] = useState(0)
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false)

  // Schema editor state
  const [editorMode, setEditorMode] = useState<SchemaEditorMode>('visual')
  const [schemaProperties, setSchemaProperties] = useState<SchemaProperty[]>([])
  const [rawSchema, setRawSchema] = useState('{\n  "type": "object",\n  "properties": {}\n}')
  const [enumRawText, setEnumRawText] = useState<Record<string, string>>({})
  const [schemaError, setSchemaError] = useState<string | null>(null)
  const [expandedProps, setExpandedProps] = useState<Set<string>>(new Set())

  // Validation
  const [validationErrors, setValidationErrors] = useState<
    Record<string, string>
  >({})
  const [touched, setTouched] = useState<Record<string, boolean>>({})

  // Populate form when editing
  useEffect(() => {
    if (existingBlueprint) {
      setName(existingBlueprint.name)
      setSlug(existingBlueprint.slug)
      setType(existingBlueprint.type)
      setDescription(existingBlueprint.description || '')
      setEnabled(existingBlueprint.enabled)
      setPriority(existingBlueprint.priority)
      setSlugManuallyEdited(true)

      try {
        const parsed =
          typeof existingBlueprint.json_schema === 'string'
            ? JSON.parse(existingBlueprint.json_schema)
            : existingBlueprint.json_schema
        const props = schemaToProperties(parsed)
        setSchemaProperties(props)
        setRawSchema(JSON.stringify(parsed, null, 2))

        // Auto-expand properties that have advanced options set
        const toExpand = props
          .filter(
            (p) =>
              p.description ||
              p.format ||
              p.defaultValue !== undefined ||
              (p.enumValues && p.enumValues.length > 0) ||
              p.minimum !== undefined ||
              p.maximum !== undefined ||
              p.minLength !== undefined ||
              p.maxLength !== undefined
          )
          .map((p) => p.id)
        if (toExpand.length > 0) {
          setExpandedProps(new Set(toExpand))
        }
      } catch {
        setRawSchema(
          typeof existingBlueprint.json_schema === 'string'
            ? existingBlueprint.json_schema
            : '{}'
        )
      }
    }
  }, [existingBlueprint])

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing && !slugManuallyEdited) {
      setSlug(toSlug(value))
    }
    handleFieldChange('name')
  }

  const handleSlugChange = (value: string) => {
    setSlug(toSlug(value))
    setSlugManuallyEdited(true)
    handleFieldChange('slug')
  }

  const handleFieldChange = (field: string) => {
    setTouched({ ...touched, [field]: true })
    if (validationErrors[field]) {
      const newErrors = { ...validationErrors }
      delete newErrors[field]
      setValidationErrors(newErrors)
    }
  }

  // Sync visual -> code
  const syncVisualToCode = useCallback(
    (props: SchemaProperty[]) => {
      const schema = buildJsonSchema(props)
      setRawSchema(JSON.stringify(schema, null, 2))
      setSchemaError(null)
    },
    []
  )

  // Sync code -> visual
  const syncCodeToVisual = useCallback((raw: string) => {
    try {
      const parsed = JSON.parse(raw)

      // Validate it's a valid JSON Schema
      const isValid = ajv.validateSchema(parsed)
      if (!isValid) {
        setSchemaError('Invalid JSON Schema structure')
        return false
      }

      // Check for unsupported nested structures
      const props = parsed.properties || {}
      const hasNested = Object.values(props).some(
        (p: unknown) =>
          (p as Record<string, unknown>).type === 'object' &&
          (p as Record<string, unknown>).properties
      )
      if (hasNested) {
        setSchemaError(
          'Visual editor does not support nested object properties. Use code mode to edit.'
        )
        return false
      }

      setSchemaProperties(schemaToProperties(parsed))
      setSchemaError(null)
      return true
    } catch {
      setSchemaError('Invalid JSON')
      return false
    }
  }, [])

  const handleEditorModeSwitch = (mode: SchemaEditorMode) => {
    if (mode === 'code' && editorMode === 'visual') {
      syncVisualToCode(schemaProperties)
    } else if (mode === 'visual' && editorMode === 'code') {
      syncCodeToVisual(rawSchema)
    }
    setEditorMode(mode)
  }

  // Schema property operations
  const addProperty = () => {
    const newProp: SchemaProperty = {
      id: generateId(),
      name: '',
      type: 'string',
      required: false,
    }
    const updated = [...schemaProperties, newProp]
    setSchemaProperties(updated)
    setExpandedProps(new Set([...expandedProps, newProp.id]))
    syncVisualToCode(updated)
  }

  const removeProperty = (id: string) => {
    const updated = schemaProperties.filter((p) => p.id !== id)
    setSchemaProperties(updated)
    syncVisualToCode(updated)
  }

  const updateProperty = (
    id: string,
    updates: Partial<SchemaProperty>
  ) => {
    const updated = schemaProperties.map((p) =>
      p.id === id ? { ...p, ...updates } : p
    )
    setSchemaProperties(updated)
    syncVisualToCode(updated)
  }

  const moveProperty = (index: number, direction: 'up' | 'down') => {
    const newIndex = direction === 'up' ? index - 1 : index + 1
    if (newIndex < 0 || newIndex >= schemaProperties.length) return
    const updated = [...schemaProperties]
    ;[updated[index], updated[newIndex]] = [
      updated[newIndex],
      updated[index],
    ]
    setSchemaProperties(updated)
    syncVisualToCode(updated)
  }

  const toggleExpandProp = (id: string) => {
    const next = new Set(expandedProps)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    setExpandedProps(next)
  }

  // Validation
  const validateForm = (): boolean => {
    const errors: Record<string, string> = {}
    if (!name.trim()) errors.name = 'Name is required'
    if (!slug.trim()) errors.slug = 'Slug is required'
    else if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(slug)) {
      errors.slug =
        'Slug must contain only lowercase letters, numbers, and hyphens'
    }
    if (!type) errors.type = 'Type is required'

    // Validate schema
    try {
      const schemaObj =
        editorMode === 'visual'
          ? buildJsonSchema(schemaProperties)
          : JSON.parse(rawSchema)
      const isValid = ajv.validateSchema(schemaObj)
      if (!isValid) {
        errors.schema = 'Invalid JSON Schema'
      }
    } catch {
      errors.schema = 'Invalid JSON in schema'
    }

    // Check for empty property names in visual mode
    if (editorMode === 'visual') {
      const emptyNames = schemaProperties.some((p) => !p.name.trim())
      if (emptyNames) {
        errors.schema = 'All schema properties must have a name'
      }
      const names = schemaProperties.map((p) => p.name.trim())
      const dupes = names.filter((n, i) => n && names.indexOf(n) !== i)
      if (dupes.length > 0) {
        errors.schema = `Duplicate property name: ${dupes[0]}`
      }
    }

    setValidationErrors(errors)
    setTouched({ name: true, slug: true, type: true, schema: true })
    return Object.keys(errors).length === 0
  }

  const handleSave = () => {
    if (isEditing && !existingBlueprint) return
    if (!validateForm()) return

    const schemaObj =
      editorMode === 'visual'
        ? buildJsonSchema(schemaProperties)
        : JSON.parse(rawSchema)

    const data: BlueprintCreate = {
      name: name.trim(),
      slug: slug.trim() || undefined,
      type,
      description: description.trim() || null,
      enabled,
      priority,
      json_schema: schemaObj,
      ...(isEditing && existingBlueprint
        ? { version: existingBlueprint.version }
        : {}),
    }
    onSave(data)
  }

  // Priority conflict check
  const conflicts = type
    ? checkPriorityConflict(
        type,
        priority,
        isEditing ? blueprintKey?.slug : undefined
      )
    : []

  if (isEditing && bpLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading blueprint...
        </div>
      </div>
    )
  }

  if (isEditing && bpError) {
    return (
      <div
        className={`flex items-center gap-3 p-4 rounded-lg border ${
          isDarkMode
            ? 'bg-red-900/20 border-red-700 text-red-400'
            : 'bg-red-50 border-red-200 text-red-700'
        }`}
      >
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load blueprint</div>
          <div className="text-sm mt-1">
            {bpError instanceof Error ? bpError.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2
            className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            {isEditing ? 'Edit Blueprint' : 'Create Blueprint'}
          </h2>
          <p
            className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {isEditing
              ? 'Update blueprint configuration and schema'
              : 'Define a new metadata schema blueprint'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={isLoading}
            className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
          >
            <X className="w-4 h-4 mr-2" />
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={isLoading}
            className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
          >
            <Save className="w-4 h-4 mr-2" />
            {isLoading
              ? 'Saving...'
              : isEditing
                ? 'Save Changes'
                : 'Create Blueprint'}
          </Button>
        </div>
      </div>

      {/* API Error Display */}
      {error && (
        <div
          className={`rounded-lg border p-4 ${
            isDarkMode
              ? 'bg-red-900/20 border-red-700'
              : 'bg-red-50 border-red-200'
          }`}
        >
          <div className="flex items-start gap-3">
            <AlertCircle
              className={`w-5 h-5 flex-shrink-0 ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
            />
            <div>
              <div
                className={`font-medium ${isDarkMode ? 'text-red-400' : 'text-red-800'}`}
              >
                Failed to save blueprint
              </div>
              <div
                className={`text-sm mt-1 ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}
              >
                {error?.response?.data?.detail ||
                  error?.message ||
                  'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Priority Conflict Warning */}
      {conflicts.length > 0 && (
        <div
          className={`rounded-lg border p-4 ${
            isDarkMode
              ? 'bg-amber-900/20 border-amber-700'
              : 'bg-amber-50 border-amber-200'
          }`}
        >
          <div className="flex items-start gap-3">
            <AlertTriangle
              className={`w-5 h-5 flex-shrink-0 ${isDarkMode ? 'text-amber-400' : 'text-amber-600'}`}
            />
            <div>
              <div
                className={`font-medium ${isDarkMode ? 'text-amber-400' : 'text-amber-800'}`}
              >
                Priority conflict
              </div>
              <div
                className={`text-sm mt-1 ${isDarkMode ? 'text-amber-300' : 'text-amber-700'}`}
              >
                Another {type} blueprint ({conflicts[0].name}) already has
                priority {priority}. Blueprints of the same type with the same
                priority may have undefined ordering.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Basic Information */}
      <div
        className={`p-6 rounded-lg border ${
          isDarkMode
            ? 'bg-gray-800 border-gray-700'
            : 'bg-white border-gray-200'
        }`}
      >
        <h3
          className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Basic Information
        </h3>

        <div className="grid grid-cols-2 gap-4">
          {/* Name */}
          <div>
            <label
              className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Name <span className="text-red-500">*</span>
            </label>
            <Input
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              onBlur={() => {
                setTouched({ ...touched, name: true })
                if (!name.trim())
                  setValidationErrors({
                    ...validationErrors,
                    name: 'Name is required',
                  })
              }}
              disabled={isLoading}
              placeholder="e.g. AWS Metadata"
              className={isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}
            />
            {touched.name && validationErrors.name && (
              <p className="text-sm text-red-600 mt-1">
                {validationErrors.name}
              </p>
            )}
          </div>

          {/* Slug */}
          <div>
            <label
              className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Slug
            </label>
            <Input
              value={slug}
              onChange={(e) => handleSlugChange(e.target.value)}
              disabled={isLoading}
              placeholder="auto-generated"
              className={`font-mono ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
            {!isEditing && !slugManuallyEdited && name && (
              <p
                className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                Auto-generated from name
              </p>
            )}
            {touched.slug && validationErrors.slug && (
              <p className="text-sm text-red-600 mt-1">
                {validationErrors.slug}
              </p>
            )}
          </div>

          {/* Type */}
          <div>
            <label
              className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Type <span className="text-red-500">*</span>
            </label>
            <select
              value={type}
              onChange={(e) => {
                setType(e.target.value)
                handleFieldChange('type')
              }}
              disabled={isLoading || isEditing}
              className={`w-full px-3 py-2 rounded-md border text-sm ${
                isDarkMode
                  ? 'bg-gray-700 border-gray-600 text-white'
                  : 'bg-white border-gray-300 text-gray-900'
              } ${isEditing ? 'opacity-60 cursor-not-allowed' : ''}`}
            >
              <option value="">Select a type...</option>
              {blueprintTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            {isEditing && (
              <p
                className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                Type cannot be changed after creation
              </p>
            )}
            {touched.type && validationErrors.type && (
              <p className="text-sm text-red-600 mt-1">
                {validationErrors.type}
              </p>
            )}
          </div>

          {/* Priority */}
          <div>
            <label
              className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Priority
            </label>
            <Input
              type="number"
              value={priority}
              onChange={(e) => setPriority(parseInt(e.target.value, 10) || 0)}
              disabled={isLoading}
              placeholder="0"
              className={isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}
            />
            <p
              className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
            >
              Higher priority blueprints are applied later and can override
              lower priority ones
            </p>
          </div>

          {/* Description */}
          <div className="col-span-2">
            <label
              className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={isLoading}
              placeholder="Brief description of what this blueprint defines"
              rows={3}
              className={`w-full px-3 py-2 rounded-md border text-sm resize-none ${
                isDarkMode
                  ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
                  : 'bg-white border-gray-300 text-gray-900 placeholder-gray-500'
              }`}
            />
          </div>

          {/* Enabled */}
          <div className="col-span-2">
            <div className="flex items-center gap-2">
              <Checkbox
                id="blueprint-enabled"
                checked={enabled}
                onCheckedChange={(checked) =>
                  setEnabled(checked === true)
                }
                disabled={isLoading}
              />
              <label
                htmlFor="blueprint-enabled"
                className={`text-sm cursor-pointer select-none ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Enabled
              </label>
            </div>
            <p
              className={`text-xs mt-1 ml-6 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
            >
              Disabled blueprints are not applied to entities
            </p>
          </div>
        </div>
      </div>

      {/* JSON Schema Editor */}
      <div
        className={`p-6 rounded-lg border ${
          isDarkMode
            ? 'bg-gray-800 border-gray-700'
            : 'bg-white border-gray-200'
        }`}
      >
        <div className="flex items-center justify-between mb-4">
          <h3
            className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            JSON Schema
          </h3>
          <div
            className={`flex items-center rounded-lg border ${
              isDarkMode ? 'border-gray-600' : 'border-gray-300'
            }`}
          >
            <button
              onClick={() => handleEditorModeSwitch('visual')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-l-lg transition-colors ${
                editorMode === 'visual'
                  ? isDarkMode
                    ? 'bg-blue-900/40 text-blue-400'
                    : 'bg-blue-50 text-[#2A4DD0]'
                  : isDarkMode
                    ? 'text-gray-400 hover:text-gray-200'
                    : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <List className="w-3.5 h-3.5" />
              Visual
            </button>
            <button
              onClick={() => handleEditorModeSwitch('code')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-r-lg transition-colors ${
                editorMode === 'code'
                  ? isDarkMode
                    ? 'bg-blue-900/40 text-blue-400'
                    : 'bg-blue-50 text-[#2A4DD0]'
                  : isDarkMode
                    ? 'text-gray-400 hover:text-gray-200'
                    : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <Code className="w-3.5 h-3.5" />
              Code
            </button>
          </div>
        </div>

        {/* Schema Error */}
        {(schemaError || (touched.schema && validationErrors.schema)) && (
          <div
            className={`mb-4 p-3 rounded-lg flex items-start gap-2 ${
              isDarkMode
                ? 'bg-red-900/20 text-red-400'
                : 'bg-red-50 text-red-700'
            }`}
          >
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <div className="text-xs">
              {schemaError || validationErrors.schema}
            </div>
          </div>
        )}

        {/* Visual Mode */}
        {editorMode === 'visual' && (
          <div className="space-y-3">
            {schemaProperties.length === 0 ? (
              <div
                className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
              >
                <div>No properties defined</div>
                <div className="text-sm mt-1">
                  Add properties to define the schema
                </div>
              </div>
            ) : (
              schemaProperties.map((prop, index) => {
                const isExpanded = expandedProps.has(prop.id)
                return (
                  <div
                    key={prop.id}
                    className={`rounded-lg border ${
                      isDarkMode
                        ? 'bg-gray-750 border-gray-600'
                        : 'bg-gray-50 border-gray-200'
                    }`}
                  >
                    {/* Property Row */}
                    <div className="flex items-center gap-3 p-3">
                      <div className="flex flex-col gap-0.5">
                        <button
                          onClick={() => moveProperty(index, 'up')}
                          disabled={index === 0}
                          className={`p-0.5 rounded ${
                            index === 0
                              ? 'opacity-30 cursor-not-allowed'
                              : isDarkMode
                                ? 'hover:bg-gray-700 text-gray-400'
                                : 'hover:bg-gray-200 text-gray-600'
                          }`}
                          title="Move up"
                        >
                          <ChevronUp className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => moveProperty(index, 'down')}
                          disabled={
                            index === schemaProperties.length - 1
                          }
                          className={`p-0.5 rounded ${
                            index === schemaProperties.length - 1
                              ? 'opacity-30 cursor-not-allowed'
                              : isDarkMode
                                ? 'hover:bg-gray-700 text-gray-400'
                                : 'hover:bg-gray-200 text-gray-600'
                          }`}
                          title="Move down"
                        >
                          <ChevronDown className="w-3 h-3" />
                        </button>
                      </div>

                      <Input
                        value={prop.name}
                        onChange={(e) =>
                          updateProperty(prop.id, {
                            name: e.target.value,
                          })
                        }
                        placeholder="Property name"
                        className={`flex-1 font-mono text-sm ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                      />

                      <select
                        value={prop.type}
                        onChange={(e) =>
                          updateProperty(prop.id, {
                            type: e.target.value as SchemaProperty['type'],
                          })
                        }
                        className={`w-28 px-2 py-2 rounded-md border text-sm ${
                          isDarkMode
                            ? 'bg-gray-700 border-gray-600 text-white'
                            : 'bg-white border-gray-300 text-gray-900'
                        }`}
                      >
                        {PROPERTY_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>

                      <div className="flex items-center gap-1.5">
                        <Checkbox
                          id={`req-${prop.id}`}
                          checked={prop.required}
                          onCheckedChange={(checked) =>
                            updateProperty(prop.id, {
                              required: checked === true,
                            })
                          }
                        />
                        <label
                          htmlFor={`req-${prop.id}`}
                          className={`text-xs cursor-pointer select-none ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                        >
                          Required
                        </label>
                      </div>

                      <button
                        onClick={() => toggleExpandProp(prop.id)}
                        className={`p-1.5 rounded text-xs ${
                          isDarkMode
                            ? 'text-gray-400 hover:bg-gray-700'
                            : 'text-gray-600 hover:bg-gray-200'
                        }`}
                        title="Advanced options"
                      >
                        {isExpanded ? (
                          <ChevronUp className="w-3.5 h-3.5" />
                        ) : (
                          <ChevronDown className="w-3.5 h-3.5" />
                        )}
                      </button>

                      <button
                        onClick={() => removeProperty(prop.id)}
                        className={`p-1.5 rounded ${
                          isDarkMode
                            ? 'text-red-400 hover:bg-red-900/20'
                            : 'text-red-600 hover:bg-red-50'
                        }`}
                        title="Remove property"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    {/* Advanced Options */}
                    {isExpanded && (
                      <div
                        className={`px-3 pb-3 pt-2 border-t space-y-3 ${
                          isDarkMode
                            ? 'border-gray-600'
                            : 'border-gray-200'
                        }`}
                      >
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label
                              className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                            >
                              Description
                            </label>
                            <Input
                              value={prop.description || ''}
                              onChange={(e) =>
                                updateProperty(prop.id, {
                                  description: e.target.value || undefined,
                                })
                              }
                              placeholder="Property description"
                              className={`text-sm ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                            />
                          </div>
                          <div>
                            <label
                              className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                            >
                              Default Value
                            </label>
                            <Input
                              value={prop.defaultValue || ''}
                              onChange={(e) =>
                                updateProperty(prop.id, {
                                  defaultValue:
                                    e.target.value || undefined,
                                })
                              }
                              placeholder="Default value"
                              className={`text-sm ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                            />
                          </div>
                        </div>

                        {prop.type === 'string' && (
                          <div className="grid grid-cols-3 gap-3">
                            <div>
                              <label
                                className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                              >
                                Format
                              </label>
                              <select
                                value={prop.format || ''}
                                onChange={(e) =>
                                  updateProperty(prop.id, {
                                    format:
                                      e.target.value || undefined,
                                  })
                                }
                                className={`w-full px-2 py-2 rounded-md border text-sm ${
                                  isDarkMode
                                    ? 'bg-gray-700 border-gray-600 text-white'
                                    : 'bg-white border-gray-300 text-gray-900'
                                }`}
                              >
                                {STRING_FORMATS.map((f) => (
                                  <option key={f} value={f}>
                                    {f || '(none)'}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div>
                              <label
                                className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                              >
                                Min Length
                              </label>
                              <Input
                                type="number"
                                value={prop.minLength ?? ''}
                                onChange={(e) =>
                                  updateProperty(prop.id, {
                                    minLength: e.target.value
                                      ? parseInt(e.target.value, 10)
                                      : undefined,
                                  })
                                }
                                className={`text-sm ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                              />
                            </div>
                            <div>
                              <label
                                className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                              >
                                Max Length
                              </label>
                              <Input
                                type="number"
                                value={prop.maxLength ?? ''}
                                onChange={(e) =>
                                  updateProperty(prop.id, {
                                    maxLength: e.target.value
                                      ? parseInt(e.target.value, 10)
                                      : undefined,
                                  })
                                }
                                className={`text-sm ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                              />
                            </div>
                          </div>
                        )}

                        {(prop.type === 'integer' ||
                          prop.type === 'number') && (
                          <div className="grid grid-cols-2 gap-3">
                            <div>
                              <label
                                className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                              >
                                Minimum
                              </label>
                              <Input
                                type="number"
                                value={prop.minimum ?? ''}
                                onChange={(e) =>
                                  updateProperty(prop.id, {
                                    minimum: e.target.value
                                      ? Number(e.target.value)
                                      : undefined,
                                  })
                                }
                                className={`text-sm ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                              />
                            </div>
                            <div>
                              <label
                                className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                              >
                                Maximum
                              </label>
                              <Input
                                type="number"
                                value={prop.maximum ?? ''}
                                onChange={(e) =>
                                  updateProperty(prop.id, {
                                    maximum: e.target.value
                                      ? Number(e.target.value)
                                      : undefined,
                                  })
                                }
                                className={`text-sm ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                              />
                            </div>
                          </div>
                        )}

                        <div>
                          <label
                            className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                          >
                            Enum Values (comma-separated)
                          </label>
                          <Input
                            value={
                              enumRawText[prop.id] ??
                              prop.enumValues?.join(', ') ??
                              ''
                            }
                            onChange={(e) =>
                              setEnumRawText({
                                ...enumRawText,
                                [prop.id]: e.target.value,
                              })
                            }
                            onBlur={() => {
                              const raw = enumRawText[prop.id]
                              if (raw !== undefined) {
                                const parsed = raw
                                  ? raw
                                      .split(',')
                                      .map((v) => v.trim())
                                      .filter(Boolean)
                                  : undefined
                                updateProperty(prop.id, {
                                  enumValues:
                                    parsed && parsed.length > 0
                                      ? parsed
                                      : undefined,
                                })
                                const next = { ...enumRawText }
                                delete next[prop.id]
                                setEnumRawText(next)
                              }
                            }}
                            placeholder="e.g. small, medium, large"
                            className={`text-sm ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )
              })
            )}

            <Button
              onClick={addProperty}
              variant="outline"
              className={`w-full ${isDarkMode ? 'border-gray-600 text-gray-300 hover:bg-gray-700' : ''}`}
            >
              <Plus className="w-4 h-4 mr-2" />
              Add Property
            </Button>
          </div>
        )}

        {/* Code Mode */}
        {editorMode === 'code' && (
          <textarea
            value={rawSchema}
            onChange={(e) => {
              setRawSchema(e.target.value)
              setSchemaError(null)
            }}
            onBlur={() => syncCodeToVisual(rawSchema)}
            rows={20}
            spellCheck={false}
            className={`w-full px-4 py-3 rounded-md border text-sm font-mono resize-y ${
              isDarkMode
                ? 'bg-gray-900 border-gray-600 text-gray-200'
                : 'bg-gray-50 border-gray-300 text-gray-900'
            }`}
          />
        )}
      </div>
    </div>
  )
}

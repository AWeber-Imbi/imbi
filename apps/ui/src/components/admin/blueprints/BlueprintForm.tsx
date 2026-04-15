import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Save,
  X,
  AlertCircle,
  Plus,
  Trash2,
  ChevronUp,
  ChevronDown,
  Code,
  Filter,
  List,
} from 'lucide-react'
import Ajv from 'ajv'
import { Button } from '@/components/ui/button'
import { CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  getBlueprint,
  listEnvironments,
  listProjectTypes,
} from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import { parseFilterFromBlueprint } from '@/lib/utils'
import type { BlueprintCreate, BlueprintFilter, SchemaProperty } from '@/types'

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
}

type SchemaEditorMode = 'visual' | 'code'

// Known relationships keyed by "Source:Target"
const RELATIONSHIP_MAP: Record<string, string[]> = {
  'Project:Environment': ['DEPLOYED_IN'],
  'Project:ProjectType': ['TYPE'],
  'Project:Team': ['OWNED_BY'],
  'Project:Project': ['DEPENDS_ON'],
  'Team:Organization': ['BELONGS_TO'],
  'Environment:Organization': ['BELONGS_TO'],
  'ProjectType:Organization': ['BELONGS_TO'],
  'ThirdPartyService:Organization': ['BELONGS_TO'],
}

function getRelationshipTypes(source: string, target: string): string[] {
  if (!source || !target) {
    // Show all unique types when pair not yet selected
    const all = new Set<string>()
    for (const types of Object.values(RELATIONSHIP_MAP)) {
      for (const t of types) all.add(t)
    }
    return Array.from(all).sort()
  }
  return RELATIONSHIP_MAP[`${source}:${target}`] || []
}

function toTitleCase(value: string): string {
  return value
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

const PROPERTY_TYPES: SchemaProperty['type'][] = [
  'string',
  'integer',
  'number',
  'boolean',
  'array',
  'object',
]

const STRING_FORMATS = [
  '',
  'date',
  'date-time',
  'email',
  'uri',
  'uri-reference',
  'hostname',
  'ipv4',
  'ipv6',
  'uuid',
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

function buildJsonSchema(
  properties: SchemaProperty[],
): Record<string, unknown> {
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

    const uiEntries: [string, Record<string, string> | undefined][] = [
      ['color-map', prop.colorMap],
      ['icon-map', prop.iconMap],
      ['color-range', prop.colorRange],
      ['icon-range', prop.iconRange],
      ['color-age', prop.colorAge],
      ['icon-age', prop.iconAge],
    ]
    const xUiObj: Record<string, unknown> = {}
    if (prop.editable === false) xUiObj['editable'] = false
    for (const [key, map] of uiEntries) {
      if (map && Object.keys(map).length > 0) xUiObj[key] = map
    }
    if (Object.keys(xUiObj).length > 0) {
      propSchema['x-ui'] = xUiObj
    }

    props[prop.name] = propSchema
    if (prop.required) required.push(prop.name)
  }

  if (required.length > 0) schema.required = required
  return schema
}

function schemaToProperties(schema: Record<string, unknown>): SchemaProperty[] {
  const props = (schema.properties || {}) as Record<
    string,
    Record<string, unknown>
  >
  const required = (schema.required || []) as string[]
  const result: SchemaProperty[] = []

  for (const [name, propSchema] of Object.entries(props)) {
    const xUi = propSchema['x-ui'] as Record<string, unknown> | undefined
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
      editable: xUi?.['editable'] === false ? false : undefined,
      colorMap: xUi?.['color-map'] as Record<string, string> | undefined,
      iconMap: xUi?.['icon-map'] as Record<string, string> | undefined,
      colorRange: xUi?.['color-range'] as Record<string, string> | undefined,
      iconRange: xUi?.['icon-range'] as Record<string, string> | undefined,
      colorAge: xUi?.['color-age'] as Record<string, string> | undefined,
      iconAge: xUi?.['icon-age'] as Record<string, string> | undefined,
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

  // Fetch available entities for filter checkboxes
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug

  const { data: availableProjectTypes = [], isLoading: ptLoading } = useQuery({
    queryKey: ['projectTypes', orgSlug],
    queryFn: () => listProjectTypes(orgSlug!),
    enabled: !!orgSlug,
  })

  const { data: availableEnvironments = [], isLoading: envLoading } = useQuery({
    queryKey: ['environments', orgSlug],
    queryFn: () => listEnvironments(orgSlug!),
    enabled: !!orgSlug,
  })

  // Form state
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [kind, setKind] = useState<'node' | 'relationship'>('node')
  const [type, setType] = useState('')
  const [source, setSource] = useState('')
  const [target, setTarget] = useState('')
  const [edge, setEdge] = useState('')
  const [description, setDescription] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [priority, setPriority] = useState(0)
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false)

  // Filter state
  const [filterEnabled, setFilterEnabled] = useState(false)
  const [selectedProjectTypes, setSelectedProjectTypes] = useState<Set<string>>(
    new Set(),
  )
  const [selectedEnvironments, setSelectedEnvironments] = useState<Set<string>>(
    new Set(),
  )

  // Schema editor state
  const [editorMode, setEditorMode] = useState<SchemaEditorMode>('visual')
  const [schemaProperties, setSchemaProperties] = useState<SchemaProperty[]>([])
  const [rawSchema, setRawSchema] = useState(
    '{\n  "type": "object",\n  "properties": {}\n}',
  )
  const [enumRawText, setEnumRawText] = useState<Record<string, string>>({})
  // Unified UI map editing state: keyed by "mapType:propId"
  // e.g. "colorMap:abc123" -> [["true", "green"], ["false", "red"]]
  const [uiMapEntries, setUiMapEntries] = useState<
    Record<string, [string, string][]>
  >({})
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
      setKind(existingBlueprint.kind || 'node')
      setType(existingBlueprint.type || '')
      setSource(existingBlueprint.source || '')
      setTarget(existingBlueprint.target || '')
      setEdge(existingBlueprint.edge || '')
      setDescription(existingBlueprint.description || '')
      setEnabled(existingBlueprint.enabled)
      setPriority(existingBlueprint.priority)
      setSlugManuallyEdited(true)
      const f = parseFilterFromBlueprint(existingBlueprint.filter)
      if (f) {
        setFilterEnabled(true)
        if (f.project_type?.length > 0) {
          setSelectedProjectTypes(new Set(f.project_type))
        }
        if (f.environment?.length > 0) {
          setSelectedEnvironments(new Set(f.environment))
        }
      }

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
              p.maxLength !== undefined ||
              [
                p.colorMap,
                p.iconMap,
                p.colorRange,
                p.iconRange,
                p.colorAge,
                p.iconAge,
              ].some((m) => m && Object.keys(m).length > 0),
          )
          .map((p) => p.id)
        if (toExpand.length > 0) {
          setExpandedProps(new Set(toExpand))
        }

        // Initialise UI map editing state from loaded properties
        const mapTypes = [
          'colorMap',
          'iconMap',
          'colorRange',
          'iconRange',
          'colorAge',
          'iconAge',
        ] as const
        const initialUiMapEntries: Record<string, [string, string][]> = {}
        for (const p of props) {
          for (const mt of mapTypes) {
            const map = p[mt]
            if (map && Object.keys(map).length > 0) {
              initialUiMapEntries[`${mt}:${p.id}`] = Object.entries(map) as [
                string,
                string,
              ][]
            }
          }
        }
        if (Object.keys(initialUiMapEntries).length > 0) {
          setUiMapEntries(initialUiMapEntries)
        }
      } catch {
        setRawSchema(
          typeof existingBlueprint.json_schema === 'string'
            ? existingBlueprint.json_schema
            : '{}',
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
  const syncVisualToCode = useCallback((props: SchemaProperty[]) => {
    const schema = buildJsonSchema(props)
    setRawSchema(JSON.stringify(schema, null, 2))
    setSchemaError(null)
  }, [])

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
          (p as Record<string, unknown>).properties,
      )
      if (hasNested) {
        setSchemaError(
          'Visual editor does not support nested object properties. Use code mode to edit.',
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

  const updateProperty = (id: string, updates: Partial<SchemaProperty>) => {
    const updated = schemaProperties.map((p) =>
      p.id === id ? { ...p, ...updates } : p,
    )
    setSchemaProperties(updated)
    syncVisualToCode(updated)
  }

  const moveProperty = (index: number, direction: 'up' | 'down') => {
    const newIndex = direction === 'up' ? index - 1 : index + 1
    if (newIndex < 0 || newIndex >= schemaProperties.length) return
    const updated = [...schemaProperties]
    ;[updated[index], updated[newIndex]] = [updated[newIndex], updated[index]]
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
    if (kind === 'node') {
      if (!type) errors.type = 'Type is required'
    } else {
      if (!source.trim()) errors.source = 'Source is required'
      if (!target.trim()) errors.target = 'Target is required'
      if (!edge.trim()) errors.edge = 'Edge is required'
    }

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
    setTouched({
      name: true,
      slug: true,
      type: true,
      schema: true,
      source: true,
      target: true,
      edge: true,
    })
    return Object.keys(errors).length === 0
  }

  const handleSave = () => {
    if (isEditing && !existingBlueprint) return
    if (!validateForm()) return

    const schemaObj =
      editorMode === 'visual'
        ? buildJsonSchema(schemaProperties)
        : JSON.parse(rawSchema)

    let filterObj: BlueprintFilter | null = null
    if (filterEnabled) {
      const ptArr = Array.from(selectedProjectTypes)
      const envArr = Array.from(selectedEnvironments)
      if (ptArr.length > 0 || envArr.length > 0) {
        filterObj = {
          project_type: ptArr,
          environment: envArr,
        }
      }
    }

    const data: BlueprintCreate = {
      name: name.trim(),
      slug: slug.trim() || undefined,
      kind,
      ...(kind === 'node'
        ? { type }
        : {
            type: null,
            source: source.trim(),
            target: target.trim(),
            edge: edge.trim(),
          }),
      description: description.trim() || null,
      enabled,
      priority,
      filter: filterObj,
      json_schema: schemaObj,
      ...(isEditing && existingBlueprint
        ? { version: existingBlueprint.version }
        : {}),
    }
    onSave(data)
  }

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
        className={`flex items-center gap-3 rounded-lg border p-4 ${
          isDarkMode
            ? 'border-red-700 bg-red-900/20 text-red-400'
            : 'border-red-200 bg-red-50 text-red-700'
        }`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load blueprint</div>
          <div className="mt-1 text-sm">
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
          <CardTitle>
            {isEditing ? 'Edit Blueprint' : 'Create Blueprint'}
          </CardTitle>
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
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={isLoading}
            className="bg-amber-border text-white hover:bg-amber-border-strong"
          >
            <Save className="mr-2 h-4 w-4" />
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
              ? 'border-red-700 bg-red-900/20'
              : 'border-red-200 bg-red-50'
          }`}
        >
          <div className="flex items-start gap-3">
            <AlertCircle
              className={`h-5 w-5 flex-shrink-0 ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
            />
            <div>
              <div
                className={`font-medium ${isDarkMode ? 'text-red-400' : 'text-red-800'}`}
              >
                Failed to save blueprint
              </div>
              <div
                className={`mt-1 text-sm ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}
              >
                {(() => {
                  const detail = error?.response?.data?.detail
                  if (Array.isArray(detail)) {
                    return detail
                      .map(
                        (e: { msg?: string; loc?: Array<string | number> }) => {
                          const field =
                            e.loc
                              ?.filter((segment) => segment !== 'body')
                              .map(String)
                              .join('.') || 'field'
                          return e.msg
                            ? `${field}: ${e.msg}`
                            : JSON.stringify(e)
                        },
                      )
                      .join('; ')
                  }
                  return typeof detail === 'string'
                    ? detail
                    : error?.message || 'An error occurred'
                })()}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Basic Information */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <h3
          className={`mb-4 text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Basic Information
        </h3>

        <div className="grid grid-cols-2 gap-4">
          {/* Name */}
          <div>
            <label
              className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
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
              className={
                isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
              }
            />
            {touched.name && validationErrors.name && (
              <p className="mt-1 text-sm text-red-600">
                {validationErrors.name}
              </p>
            )}
          </div>

          {/* Slug */}
          {!isEditing && (
            <div>
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Slug
              </label>
              <Input
                value={slug}
                onChange={(e) => handleSlugChange(e.target.value)}
                disabled={isLoading}
                placeholder="auto-generated"
                className={`font-mono ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
              />
              {!slugManuallyEdited && name && (
                <p
                  className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                >
                  Auto-generated from name
                </p>
              )}
              {touched.slug && validationErrors.slug && (
                <p className="mt-1 text-sm text-red-600">
                  {validationErrors.slug}
                </p>
              )}
            </div>
          )}

          {/* Kind */}
          <div>
            <label
              className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Kind <span className="text-red-500">*</span>
            </label>
            <select
              value={kind}
              onChange={(e) =>
                setKind(e.target.value as 'node' | 'relationship')
              }
              disabled={isLoading || isEditing}
              className={`w-full rounded-md border px-3 py-2 text-sm ${
                isDarkMode
                  ? 'border-gray-600 bg-gray-700 text-white'
                  : 'border-gray-300 bg-white text-gray-900'
              } ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
            >
              <option value="node">Object</option>
              <option value="relationship">Relationship</option>
            </select>
            {isEditing && (
              <p
                className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                Kind cannot be changed after creation
              </p>
            )}
          </div>

          {/* Type (node) or Source/Target/Edge (relationship) */}
          {kind === 'node' ? (
            <div>
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
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
                className={`w-full rounded-md border px-3 py-2 text-sm ${
                  isDarkMode
                    ? 'border-gray-600 bg-gray-700 text-white'
                    : 'border-gray-300 bg-white text-gray-900'
                } ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
              >
                <option value="">Select a type...</option>
                {blueprintTypes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              {touched.type && validationErrors.type && (
                <p className="mt-1 text-sm text-red-600">
                  {validationErrors.type}
                </p>
              )}
            </div>
          ) : (
            <div className="col-span-2 grid grid-cols-[1fr_auto_1fr_auto_1fr] items-end gap-2">
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Source <span className="text-red-500">*</span>
                </label>
                <select
                  value={source}
                  onChange={(e) => {
                    setSource(e.target.value)
                    handleFieldChange('source')
                    const valid = getRelationshipTypes(e.target.value, target)
                    if (edge && !valid.includes(edge)) setEdge('')
                  }}
                  disabled={isLoading || isEditing}
                  className={`w-full rounded-md border px-3 py-2 text-sm ${
                    isDarkMode
                      ? 'border-gray-600 bg-gray-700 text-white'
                      : 'border-gray-300 bg-white text-gray-900'
                  } ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
                >
                  <option value="">Select source...</option>
                  {blueprintTypes.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                {touched.source && validationErrors.source && (
                  <p className="mt-1 text-sm text-red-600">
                    {validationErrors.source}
                  </p>
                )}
              </div>
              <div
                className={`pb-2 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                →
              </div>
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Relationship Type <span className="text-red-500">*</span>
                </label>
                {source &&
                target &&
                (getRelationshipTypes(source, target).length === 0 ||
                  (edge &&
                    !getRelationshipTypes(source, target).includes(edge))) ? (
                  <Input
                    value={edge}
                    onChange={(e) => {
                      setEdge(e.target.value)
                      handleFieldChange('edge')
                    }}
                    disabled={isLoading || isEditing}
                    placeholder="Enter relationship type..."
                    className={`w-full ${
                      isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
                    }`}
                  />
                ) : (
                  <select
                    value={edge}
                    onChange={(e) => {
                      setEdge(e.target.value)
                      handleFieldChange('edge')
                    }}
                    disabled={isLoading || isEditing || !source || !target}
                    className={`w-full rounded-md border px-3 py-2 text-sm ${
                      isDarkMode
                        ? 'border-gray-600 bg-gray-700 text-white'
                        : 'border-gray-300 bg-white text-gray-900'
                    } ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
                  >
                    <option value="">
                      {source && target
                        ? 'Select type...'
                        : 'Pick source & target first'}
                    </option>
                    {getRelationshipTypes(source, target).map((rt) => (
                      <option key={rt} value={rt}>
                        {toTitleCase(rt)}
                      </option>
                    ))}
                  </select>
                )}
                {touched.edge && validationErrors.edge && (
                  <p className="mt-1 text-sm text-red-600">
                    {validationErrors.edge}
                  </p>
                )}
              </div>
              <div
                className={`pb-2 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                →
              </div>
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Target <span className="text-red-500">*</span>
                </label>
                <select
                  value={target}
                  onChange={(e) => {
                    setTarget(e.target.value)
                    handleFieldChange('target')
                    const valid = getRelationshipTypes(source, e.target.value)
                    if (edge && !valid.includes(edge)) setEdge('')
                  }}
                  disabled={isLoading || isEditing}
                  className={`w-full rounded-md border px-3 py-2 text-sm ${
                    isDarkMode
                      ? 'border-gray-600 bg-gray-700 text-white'
                      : 'border-gray-300 bg-white text-gray-900'
                  } ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
                >
                  <option value="">Select target...</option>
                  {blueprintTypes.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                {touched.target && validationErrors.target && (
                  <p className="mt-1 text-sm text-red-600">
                    {validationErrors.target}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Priority */}
          <div>
            <label
              className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Priority
            </label>
            <Input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={String(priority)}
              onChange={(e) => {
                const val = e.target.value.replace(/[^0-9]/g, '')
                setPriority(val === '' ? 0 : parseInt(val, 10))
              }}
              disabled={isLoading}
              placeholder="0"
              className={
                isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
              }
            />
            <p
              className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
            >
              Higher priority blueprints are applied later and can override
              lower priority ones
            </p>
          </div>

          {/* Description */}
          <div className="col-span-2">
            <label
              className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={isLoading}
              placeholder="Brief description of what this blueprint defines"
              rows={3}
              className={`w-full resize-none rounded-md border px-3 py-2 text-sm ${
                isDarkMode
                  ? 'border-gray-600 bg-gray-700 text-white placeholder-gray-400'
                  : 'border-gray-300 bg-white text-gray-900 placeholder-gray-500'
              }`}
            />
          </div>

          {/* Enabled */}
          <div className="col-span-2">
            <div className="flex items-center gap-2">
              <Checkbox
                id="blueprint-enabled"
                checked={enabled}
                onCheckedChange={(checked) => setEnabled(checked === true)}
                disabled={isLoading}
              />
              <label
                htmlFor="blueprint-enabled"
                className={`cursor-pointer select-none text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Enabled
              </label>
            </div>
            <p
              className={`ml-6 mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
            >
              Disabled blueprints are not applied to entities
            </p>
          </div>
        </div>
      </div>

      {/* Conditional Filter */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Filter
              className={`h-4 w-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            />
            <h3
              className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
            >
              Conditional Filter
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="filter-enabled"
              checked={filterEnabled}
              onCheckedChange={(checked) => {
                setFilterEnabled(checked === true)
                if (!checked) {
                  setSelectedProjectTypes(new Set())
                  setSelectedEnvironments(new Set())
                }
              }}
              disabled={isLoading}
            />
            <label
              htmlFor="filter-enabled"
              className={`cursor-pointer select-none text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Enable filter
            </label>
          </div>
        </div>

        {filterEnabled ? (
          <div className="space-y-5">
            <p
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              Select which project types and environments this blueprint applies
              to. Leave a section unchecked to apply to all.
            </p>

            {/* Project Type filter */}
            <div>
              <label
                className={`mb-2 block text-sm font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Project Types
              </label>
              {ptLoading ? (
                <p
                  className={`text-xs italic ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                >
                  Loading project types...
                </p>
              ) : availableProjectTypes.length === 0 ? (
                <p
                  className={`text-xs italic ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                >
                  No project types available
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                  {availableProjectTypes.map((pt) => (
                    <div key={pt.slug} className="flex items-center gap-2">
                      <Checkbox
                        id={`filter-pt-${pt.slug}`}
                        checked={selectedProjectTypes.has(pt.slug)}
                        onCheckedChange={(checked) => {
                          const next = new Set(selectedProjectTypes)
                          if (checked) {
                            next.add(pt.slug)
                          } else {
                            next.delete(pt.slug)
                          }
                          setSelectedProjectTypes(next)
                        }}
                        disabled={isLoading}
                      />
                      <label
                        htmlFor={`filter-pt-${pt.slug}`}
                        className={`cursor-pointer select-none text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                      >
                        {pt.name}
                      </label>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Environment filter */}
            <div>
              <label
                className={`mb-2 block text-sm font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Environments
              </label>
              {envLoading ? (
                <p
                  className={`text-xs italic ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                >
                  Loading environments...
                </p>
              ) : availableEnvironments.length === 0 ? (
                <p
                  className={`text-xs italic ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                >
                  No environments available
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                  {availableEnvironments.map((env) => (
                    <div key={env.slug} className="flex items-center gap-2">
                      <Checkbox
                        id={`filter-env-${env.slug}`}
                        checked={selectedEnvironments.has(env.slug)}
                        onCheckedChange={(checked) => {
                          const next = new Set(selectedEnvironments)
                          if (checked) {
                            next.add(env.slug)
                          } else {
                            next.delete(env.slug)
                          }
                          setSelectedEnvironments(next)
                        }}
                        disabled={isLoading}
                      />
                      <label
                        htmlFor={`filter-env-${env.slug}`}
                        className={`cursor-pointer select-none text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                      >
                        {env.name}
                      </label>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <p
            className={`text-sm ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
          >
            No filter configured. This blueprint will apply to all entities of
            its type.
          </p>
        )}
      </div>

      {/* JSON Schema Editor */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3
            className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
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
              className={`flex items-center gap-1.5 rounded-l-lg px-3 py-1.5 text-sm transition-colors ${
                editorMode === 'visual'
                  ? isDarkMode
                    ? 'bg-blue-900/40 text-blue-400'
                    : 'bg-blue-50 text-[#2A4DD0]'
                  : isDarkMode
                    ? 'text-gray-400 hover:text-gray-200'
                    : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <List className="h-3.5 w-3.5" />
              Visual
            </button>
            <button
              onClick={() => handleEditorModeSwitch('code')}
              className={`flex items-center gap-1.5 rounded-r-lg px-3 py-1.5 text-sm transition-colors ${
                editorMode === 'code'
                  ? isDarkMode
                    ? 'bg-blue-900/40 text-blue-400'
                    : 'bg-blue-50 text-[#2A4DD0]'
                  : isDarkMode
                    ? 'text-gray-400 hover:text-gray-200'
                    : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <Code className="h-3.5 w-3.5" />
              Code
            </button>
          </div>
        </div>

        {/* Schema Error */}
        {(schemaError || (touched.schema && validationErrors.schema)) && (
          <div
            className={`mb-4 flex items-start gap-2 rounded-lg p-3 ${
              isDarkMode
                ? 'bg-red-900/20 text-red-400'
                : 'bg-red-50 text-red-700'
            }`}
          >
            <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
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
                className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
              >
                <div>No properties defined</div>
                <div className="mt-1 text-sm">
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
                        ? 'border-gray-600 bg-gray-700'
                        : 'border-gray-200 bg-gray-50'
                    }`}
                  >
                    {/* Property Row */}
                    <div className="flex items-center gap-3 p-3">
                      <div className="flex flex-col gap-0.5">
                        <TooltipProvider delayDuration={200}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="inline-flex">
                                <button
                                  type="button"
                                  aria-label="Move property up"
                                  onClick={() => moveProperty(index, 'up')}
                                  disabled={index === 0}
                                  className={`rounded p-0.5 ${
                                    index === 0
                                      ? 'cursor-not-allowed opacity-30'
                                      : isDarkMode
                                        ? 'text-gray-400 hover:bg-gray-700'
                                        : 'text-gray-600 hover:bg-gray-200'
                                  }`}
                                >
                                  <ChevronUp className="h-3 w-3" />
                                </button>
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p>Move up</p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                        <TooltipProvider delayDuration={200}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="inline-flex">
                                <button
                                  type="button"
                                  aria-label="Move property down"
                                  onClick={() => moveProperty(index, 'down')}
                                  disabled={
                                    index === schemaProperties.length - 1
                                  }
                                  className={`rounded p-0.5 ${
                                    index === schemaProperties.length - 1
                                      ? 'cursor-not-allowed opacity-30'
                                      : isDarkMode
                                        ? 'text-gray-400 hover:bg-gray-700'
                                        : 'text-gray-600 hover:bg-gray-200'
                                  }`}
                                >
                                  <ChevronDown className="h-3 w-3" />
                                </button>
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p>Move down</p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </div>

                      <Input
                        value={prop.name}
                        onChange={(e) =>
                          updateProperty(prop.id, {
                            name: e.target.value,
                          })
                        }
                        placeholder="Property name"
                        className={`flex-1 font-mono text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                      />

                      <select
                        value={prop.type}
                        onChange={(e) =>
                          updateProperty(prop.id, {
                            type: e.target.value as SchemaProperty['type'],
                          })
                        }
                        className={`w-28 rounded-md border px-2 py-2 text-sm ${
                          isDarkMode
                            ? 'border-gray-600 bg-gray-700 text-white'
                            : 'border-gray-300 bg-white text-gray-900'
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
                          className={`cursor-pointer select-none text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                        >
                          Required
                        </label>
                      </div>

                      <div className="flex items-center gap-1.5">
                        <Checkbox
                          id={`editable-${prop.id}`}
                          checked={prop.editable !== false}
                          onCheckedChange={(checked) =>
                            updateProperty(prop.id, {
                              editable: checked === true ? undefined : false,
                            })
                          }
                        />
                        <label
                          htmlFor={`editable-${prop.id}`}
                          className={`cursor-pointer select-none text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                        >
                          Editable
                        </label>
                      </div>

                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label={
                                isExpanded
                                  ? 'Collapse advanced options'
                                  : 'Expand advanced options'
                              }
                              onClick={() => toggleExpandProp(prop.id)}
                              className={`rounded p-1.5 text-xs ${
                                isDarkMode
                                  ? 'text-gray-400 hover:bg-gray-700'
                                  : 'text-gray-600 hover:bg-gray-200'
                              }`}
                            >
                              {isExpanded ? (
                                <ChevronUp className="h-3.5 w-3.5" />
                              ) : (
                                <ChevronDown className="h-3.5 w-3.5" />
                              )}
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Advanced options</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>

                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label="Remove property"
                              onClick={() => removeProperty(prop.id)}
                              className={`rounded p-1.5 ${
                                isDarkMode
                                  ? 'text-red-400 hover:bg-red-900/20'
                                  : 'text-red-600 hover:bg-red-50'
                              }`}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Remove property</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>

                    {/* Advanced Options */}
                    {isExpanded && (
                      <div
                        className={`space-y-3 border-t px-3 pb-3 pt-2 ${
                          isDarkMode ? 'border-gray-600' : 'border-gray-200'
                        }`}
                      >
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label
                              className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
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
                              className={`text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                            />
                          </div>
                          <div>
                            <label
                              className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                            >
                              Default Value
                            </label>
                            <Input
                              value={prop.defaultValue || ''}
                              onChange={(e) =>
                                updateProperty(prop.id, {
                                  defaultValue: e.target.value || undefined,
                                })
                              }
                              placeholder="Default value"
                              className={`text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                            />
                          </div>
                        </div>

                        {prop.type === 'string' && (
                          <div className="grid grid-cols-3 gap-3">
                            <div>
                              <label
                                className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                              >
                                Format
                              </label>
                              <select
                                value={prop.format || ''}
                                onChange={(e) =>
                                  updateProperty(prop.id, {
                                    format: e.target.value || undefined,
                                  })
                                }
                                className={`w-full rounded-md border px-2 py-2 text-sm ${
                                  isDarkMode
                                    ? 'border-gray-600 bg-gray-700 text-white'
                                    : 'border-gray-300 bg-white text-gray-900'
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
                                className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
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
                                className={`text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                              />
                            </div>
                            <div>
                              <label
                                className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
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
                                className={`text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                              />
                            </div>
                          </div>
                        )}

                        {(prop.type === 'integer' ||
                          prop.type === 'number') && (
                          <div className="grid grid-cols-2 gap-3">
                            <div>
                              <label
                                className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
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
                                className={`text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                              />
                            </div>
                            <div>
                              <label
                                className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
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
                                className={`text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                              />
                            </div>
                          </div>
                        )}

                        <div>
                          <label
                            className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
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
                            className={`text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                          />
                        </div>

                        {/* UI Maps */}
                        {[
                          {
                            mapType: 'colorMap' as const,
                            label: 'Color Map',
                            keyPh: 'value',
                            valPh: 'e.g. green',
                            defaultVal: 'green',
                            isColor: true,
                          },
                          {
                            mapType: 'iconMap' as const,
                            label: 'Icon Map',
                            keyPh: 'value',
                            valPh: 'e.g. circle-check-big',
                            defaultVal: '',
                            isColor: false,
                          },
                          {
                            mapType: 'colorRange' as const,
                            label: 'Color Range',
                            keyPh: 'e.g. >=90',
                            valPh: 'e.g. green',
                            defaultVal: 'green',
                            isColor: true,
                          },
                          {
                            mapType: 'iconRange' as const,
                            label: 'Icon Range',
                            keyPh: 'e.g. >=90',
                            valPh: 'e.g. check-circle',
                            defaultVal: '',
                            isColor: false,
                          },
                          {
                            mapType: 'colorAge' as const,
                            label: 'Color Age',
                            keyPh: 'e.g. >30d',
                            valPh: 'e.g. red',
                            defaultVal: 'red',
                            isColor: true,
                          },
                          {
                            mapType: 'iconAge' as const,
                            label: 'Icon Age',
                            keyPh: 'e.g. >30d',
                            valPh: 'e.g. alert-triangle',
                            defaultVal: '',
                            isColor: false,
                          },
                        ].map(
                          ({
                            mapType,
                            label: mapLabel,
                            keyPh,
                            valPh,
                            defaultVal,
                            isColor,
                          }) => {
                            const stateKey = `${mapType}:${prop.id}`
                            const entries = uiMapEntries[stateKey] ?? []
                            const commit = (next: [string, string][]) => {
                              const map = Object.fromEntries(
                                next.filter(([k]) => k.trim() !== ''),
                              )
                              updateProperty(prop.id, {
                                [mapType]:
                                  Object.keys(map).length > 0 ? map : undefined,
                              })
                            }
                            return (
                              <div key={mapType}>
                                <div className="mb-1 flex items-center justify-between">
                                  <label
                                    className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                                  >
                                    {mapLabel}
                                  </label>
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setUiMapEntries({
                                        ...uiMapEntries,
                                        [stateKey]: [
                                          ...entries,
                                          ['', defaultVal],
                                        ],
                                      })
                                    }}
                                    className={`flex items-center gap-1 text-xs ${isDarkMode ? 'text-blue-400 hover:text-blue-300' : 'text-blue-600 hover:text-blue-700'}`}
                                  >
                                    <Plus className="h-3 w-3" />
                                    Add entry
                                  </button>
                                </div>
                                {entries.length === 0 ? (
                                  <p
                                    className={`text-xs italic ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                                  >
                                    No {mapLabel.toLowerCase()} entries
                                  </p>
                                ) : (
                                  <div className="space-y-1.5">
                                    {entries.map(([eKey, eVal], idx) => (
                                      <div
                                        key={idx}
                                        className="flex items-center gap-1.5"
                                      >
                                        <Input
                                          value={eKey}
                                          onChange={(e) => {
                                            const next = entries.map(
                                              (row, i): [string, string] =>
                                                i === idx
                                                  ? [e.target.value, row[1]]
                                                  : row,
                                            )
                                            setUiMapEntries({
                                              ...uiMapEntries,
                                              [stateKey]: next,
                                            })
                                          }}
                                          onBlur={() => commit(entries)}
                                          placeholder={keyPh}
                                          className={`flex-1 text-xs ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                                        />
                                        {isColor ? (
                                          <select
                                            value={eVal}
                                            onChange={(e) => {
                                              const next = entries.map(
                                                (row, i): [string, string] =>
                                                  i === idx
                                                    ? [row[0], e.target.value]
                                                    : row,
                                              )
                                              setUiMapEntries({
                                                ...uiMapEntries,
                                                [stateKey]: next,
                                              })
                                              commit(next)
                                            }}
                                            className={`rounded-md border px-2 py-1.5 text-xs ${
                                              isDarkMode
                                                ? 'border-gray-600 bg-gray-700 text-white'
                                                : 'border-gray-300 bg-white text-gray-900'
                                            }`}
                                          >
                                            {[
                                              'green',
                                              'red',
                                              'amber',
                                              'yellow',
                                              'blue',
                                              'gray',
                                            ].map((c) => (
                                              <option key={c} value={c}>
                                                {c}
                                              </option>
                                            ))}
                                          </select>
                                        ) : (
                                          <Input
                                            value={eVal}
                                            onChange={(e) => {
                                              const next = entries.map(
                                                (row, i): [string, string] =>
                                                  i === idx
                                                    ? [row[0], e.target.value]
                                                    : row,
                                              )
                                              setUiMapEntries({
                                                ...uiMapEntries,
                                                [stateKey]: next,
                                              })
                                            }}
                                            onBlur={() => commit(entries)}
                                            placeholder={valPh}
                                            className={`flex-1 text-xs ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                                          />
                                        )}
                                        <button
                                          type="button"
                                          onClick={() => {
                                            const next = entries.filter(
                                              (_, i) => i !== idx,
                                            )
                                            setUiMapEntries({
                                              ...uiMapEntries,
                                              [stateKey]: next,
                                            })
                                            commit(next)
                                          }}
                                          className={`flex-shrink-0 ${isDarkMode ? 'text-gray-500 hover:text-red-400' : 'text-gray-400 hover:text-red-500'}`}
                                        >
                                          <X className="h-3.5 w-3.5" />
                                        </button>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )
                          },
                        )}
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
              <Plus className="mr-2 h-4 w-4" />
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
            className={`w-full resize-y rounded-md border px-4 py-3 font-mono text-sm ${
              isDarkMode
                ? 'border-gray-600 bg-gray-900 text-gray-200'
                : 'border-gray-300 bg-gray-50 text-gray-900'
            }`}
          />
        )}
      </div>
    </div>
  )
}

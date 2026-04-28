import { useCallback, useEffect, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Save, X } from 'lucide-react'

import {
  getBlueprint,
  listEnvironments,
  listProjectTypes,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { parseFilterFromBlueprint } from '@/lib/utils'
import type { BlueprintCreate, BlueprintFilter, SchemaProperty } from '@/types'

import {
  ajv,
  buildJsonSchema,
  generateId,
  getRelationshipTypes,
  type SchemaEditorMode,
  schemaToProperties,
  toSlug,
  toTitleCase,
} from './blueprint-schema-utils'
import { BlueprintFilterEditor } from './BlueprintFilterEditor'
import { BlueprintSchemaEditor } from './BlueprintSchemaEditor'

interface BlueprintFormProps {
  blueprintKey: null | { slug: string; type: string }
  blueprintTypes: string[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  error?: any
  isLoading?: boolean
  onCancel: () => void
  onSave: (data: BlueprintCreate) => void
}

export function BlueprintForm({
  blueprintKey,
  blueprintTypes,
  error,
  isLoading = false,
  onCancel,
  onSave,
}: BlueprintFormProps) {
  const isEditing = !!blueprintKey

  // Fetch existing blueprint when editing
  const {
    data: existingBlueprint,
    error: bpError,
    isLoading: bpLoading,
  } = useQuery({
    enabled: isEditing,
    queryFn: ({ signal }) =>
      getBlueprint(blueprintKey!.type, blueprintKey!.slug, signal),
    queryKey: ['blueprint', blueprintKey?.type, blueprintKey?.slug],
  })

  // Fetch available entities for filter checkboxes
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug

  const {
    data: availableProjectTypes = [],
    isError: ptIsError,
    isLoading: ptLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listProjectTypes(orgSlug!, signal),
    queryKey: ['projectTypes', orgSlug],
  })

  const {
    data: availableEnvironments = [],
    isError: envIsError,
    isLoading: envLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listEnvironments(orgSlug!, signal),
    queryKey: ['environments', orgSlug],
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
  // Unified UI map editing state: keyed by "mapType:propId"
  // e.g. "colorMap:abc123" -> [["true", "green"], ["false", "red"]]
  const [uiMapEntries, setUiMapEntries] = useState<
    Record<string, [string, string][]>
  >({})
  const [schemaError, setSchemaError] = useState<null | string>(null)
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
      setSlug(existingBlueprint.slug ?? '')
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
      required: false,
      type: 'string',
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

  const moveProperty = (index: number, direction: 'down' | 'up') => {
    const newIndex = direction === 'up' ? index - 1 : index + 1
    if (newIndex < 0 || newIndex >= schemaProperties.length) return
    const updated = [...schemaProperties]
    ;[updated[index], updated[newIndex]] = [updated[newIndex], updated[index]]
    setSchemaProperties(updated)
    syncVisualToCode(updated)
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
      edge: true,
      name: true,
      schema: true,
      slug: true,
      source: true,
      target: true,
      type: true,
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
          environment: envArr,
          project_type: ptArr,
        }
      }
    }

    const data: BlueprintCreate = {
      kind,
      name: name.trim(),
      slug: slug.trim() || undefined,
      ...(kind === 'node'
        ? { type }
        : {
            edge: edge.trim(),
            source: source.trim(),
            target: target.trim(),
            type: null,
          }),
      description: description.trim() || null,
      enabled,
      filter: filterObj,
      json_schema: schemaObj,
      priority,
      ...(isEditing && existingBlueprint
        ? { version: existingBlueprint.version }
        : {}),
    }
    onSave(data)
  }

  if (isEditing && bpLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-sm text-secondary">Loading blueprint...</div>
      </div>
    )
  }

  if (isEditing && bpError) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger">
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
          <p className="mt-1 text-secondary">
            {isEditing
              ? 'Update blueprint configuration and schema'
              : 'Define a new metadata schema blueprint'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button disabled={isLoading} onClick={onCancel} variant="outline">
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={isLoading}
            onClick={handleSave}
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
        <div className="rounded-lg border border-danger bg-danger p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 flex-shrink-0 text-danger" />
            <div>
              <div className="font-medium text-danger">
                Failed to save blueprint
              </div>
              <div className="mt-1 text-sm text-danger">
                {(() => {
                  const detail = error?.response?.data?.detail
                  if (Array.isArray(detail)) {
                    return detail
                      .map(
                        (e: { loc?: Array<number | string>; msg?: string }) => {
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
      <div className="rounded-lg border border-border bg-card p-6">
        <h3 className="mb-4 text-sm font-medium text-primary">
          Basic Information
        </h3>

        <div className="grid grid-cols-2 gap-4">
          {/* Name */}
          <div>
            <label className="mb-1.5 block text-sm text-secondary">
              Name <span className="text-red-500">*</span>
            </label>
            <Input
              className=""
              disabled={isLoading}
              onBlur={() => {
                setTouched({ ...touched, name: true })
                if (!name.trim())
                  setValidationErrors({
                    ...validationErrors,
                    name: 'Name is required',
                  })
              }}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="e.g. AWS Metadata"
              value={name}
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
              <label className="mb-1.5 block text-sm text-secondary">
                Slug
              </label>
              <Input
                className="font-mono"
                disabled={isLoading}
                onChange={(e) => handleSlugChange(e.target.value)}
                placeholder="auto-generated"
                value={slug}
              />
              {!slugManuallyEdited && name && (
                <p className="mt-1 text-xs text-tertiary">
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
            <label className="mb-1.5 block text-sm text-secondary">
              Kind <span className="text-red-500">*</span>
            </label>
            <select
              className={`w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
              disabled={isLoading || isEditing}
              onChange={(e) =>
                setKind(e.target.value as 'node' | 'relationship')
              }
              value={kind}
            >
              <option value="node">Object</option>
              <option value="relationship">Relationship</option>
            </select>
            {isEditing && (
              <p className="mt-1 text-xs text-tertiary">
                Kind cannot be changed after creation
              </p>
            )}
          </div>

          {/* Type (node) or Source/Target/Edge (relationship) */}
          {kind === 'node' ? (
            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Type <span className="text-red-500">*</span>
              </label>
              <select
                className={`w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
                disabled={isLoading || isEditing}
                onChange={(e) => {
                  setType(e.target.value)
                  handleFieldChange('type')
                }}
                value={type}
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
                <label className="mb-1.5 block text-sm text-secondary">
                  Source <span className="text-red-500">*</span>
                </label>
                <select
                  className={`w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
                  disabled={isLoading || isEditing}
                  onChange={(e) => {
                    setSource(e.target.value)
                    handleFieldChange('source')
                    const valid = getRelationshipTypes(e.target.value, target)
                    if (edge && !valid.includes(edge)) setEdge('')
                  }}
                  value={source}
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
              <div className="pb-2 text-tertiary">→</div>
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Relationship Type <span className="text-red-500">*</span>
                </label>
                {source &&
                target &&
                (getRelationshipTypes(source, target).length === 0 ||
                  (edge &&
                    !getRelationshipTypes(source, target).includes(edge))) ? (
                  <Input
                    className={`w-full ${''}`}
                    disabled={isLoading || isEditing}
                    onChange={(e) => {
                      setEdge(e.target.value)
                      handleFieldChange('edge')
                    }}
                    placeholder="Enter relationship type..."
                    value={edge}
                  />
                ) : (
                  <select
                    className={`w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
                    disabled={isLoading || isEditing || !source || !target}
                    onChange={(e) => {
                      setEdge(e.target.value)
                      handleFieldChange('edge')
                    }}
                    value={edge}
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
              <div className="pb-2 text-tertiary">→</div>
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Target <span className="text-red-500">*</span>
                </label>
                <select
                  className={`w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ${isEditing ? 'cursor-not-allowed opacity-60' : ''}`}
                  disabled={isLoading || isEditing}
                  onChange={(e) => {
                    setTarget(e.target.value)
                    handleFieldChange('target')
                    const valid = getRelationshipTypes(source, e.target.value)
                    if (edge && !valid.includes(edge)) setEdge('')
                  }}
                  value={target}
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
            <label className="mb-1.5 block text-sm text-secondary">
              Priority
            </label>
            <Input
              className=""
              disabled={isLoading}
              inputMode="numeric"
              onChange={(e) => {
                const val = e.target.value.replace(/[^0-9]/g, '')
                setPriority(val === '' ? 0 : parseInt(val, 10))
              }}
              pattern="[0-9]*"
              placeholder="0"
              type="text"
              value={String(priority)}
            />
            <p className="mt-1 text-xs text-tertiary">
              Higher priority blueprints are applied later and can override
              lower priority ones
            </p>
          </div>

          {/* Description */}
          <div className="col-span-2">
            <label className="mb-1.5 block text-sm text-secondary">
              Description
            </label>
            <textarea
              className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
              disabled={isLoading}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of what this blueprint defines"
              rows={3}
              value={description}
            />
          </div>

          {/* Enabled */}
          <div className="col-span-2">
            <div className="flex items-center gap-2">
              <Checkbox
                checked={enabled}
                disabled={isLoading}
                id="blueprint-enabled"
                onCheckedChange={(checked) => setEnabled(checked === true)}
              />
              <label
                className="cursor-pointer select-none text-sm text-secondary"
                htmlFor="blueprint-enabled"
              >
                Enabled
              </label>
            </div>
            <p className="ml-6 mt-1 text-xs text-tertiary">
              Disabled blueprints are not applied to entities
            </p>
          </div>
        </div>
      </div>

      {/* Conditional Filter */}
      <BlueprintFilterEditor
        availableEnvironments={availableEnvironments}
        availableProjectTypes={availableProjectTypes}
        envIsError={envIsError}
        envLoading={envLoading}
        filterEnabled={filterEnabled}
        isLoading={isLoading}
        ptIsError={ptIsError}
        ptLoading={ptLoading}
        selectedEnvironments={selectedEnvironments}
        selectedProjectTypes={selectedProjectTypes}
        setFilterEnabled={setFilterEnabled}
        setSelectedEnvironments={setSelectedEnvironments}
        setSelectedProjectTypes={setSelectedProjectTypes}
      />

      {/* JSON Schema Editor */}
      <BlueprintSchemaEditor
        addProperty={addProperty}
        editorMode={editorMode}
        expandedProps={expandedProps}
        handleEditorModeSwitch={handleEditorModeSwitch}
        moveProperty={moveProperty}
        rawSchema={rawSchema}
        removeProperty={removeProperty}
        schemaError={schemaError}
        schemaProperties={schemaProperties}
        setExpandedProps={setExpandedProps}
        setRawSchema={setRawSchema}
        setSchemaError={setSchemaError}
        setUiMapEntries={setUiMapEntries}
        syncCodeToVisual={syncCodeToVisual}
        touched={touched}
        uiMapEntries={uiMapEntries}
        updateProperty={updateProperty}
        validationErrors={validationErrors}
      />
    </div>
  )
}

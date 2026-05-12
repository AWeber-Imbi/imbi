import { useCallback, useEffect, useState } from 'react'

import Ajv from 'ajv'
import yaml from 'js-yaml'
import { AlertCircle, FileJson, FileText } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { type DetectedFormat, detectFormat } from '@/lib/import-format'
import type { BlueprintCreate, BlueprintFilter } from '@/types'

import { ImportDialogFooter } from '../import-dialog-shared'

const ajv = new Ajv()

interface ImportBlueprintDialogProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  apiError?: any
  blueprintTypes: string[]
  isLoading?: boolean
  isOpen: boolean
  onClose: () => void
  onImport: (blueprint: BlueprintCreate) => void
}

const VALID_TYPES = new Set(['Environment', 'Project', 'ProjectType', 'Team'])

const REQUIRED_FIELDS = ['name', 'json_schema'] as const

export function ImportBlueprintDialog({
  apiError,
  blueprintTypes,
  isLoading = false,
  isOpen,
  onClose,
  onImport,
}: ImportBlueprintDialogProps) {
  const [rawInput, setRawInput] = useState('')
  const [error, setError] = useState<null | string>(null)
  const [parsedPreview, setParsedPreview] = useState<BlueprintCreate | null>(
    null,
  )
  const [detectedFormat, setDetectedFormat] =
    useState<DetectedFormat>('unknown')

  const reset = useCallback(() => {
    setRawInput('')
    setError(null)
    setParsedPreview(null)
    setDetectedFormat('unknown')
  }, [])

  // Reset state when dialog opens
  useEffect(() => {
    if (isOpen) {
      reset()
    }
  }, [isOpen, reset])

  const handleClose = useCallback(() => {
    reset()
    onClose()
  }, [reset, onClose])

  const handleInputChange = useCallback(
    (value: string) => {
      setRawInput(value)
      setError(null)
      setParsedPreview(null)

      if (!value.trim()) {
        setDetectedFormat('unknown')
        return
      }

      const fmt = detectFormat(value)
      setDetectedFormat(fmt)

      // Try to parse and validate on the fly
      try {
        let parsed: unknown
        if (fmt === 'json' || fmt === 'unknown') {
          try {
            parsed = JSON.parse(value)
          } catch {
            if (fmt === 'json') return // Still typing JSON
            // Try YAML as fallback
            try {
              parsed = yaml.load(value)
            } catch {
              return
            }
          }
        } else {
          parsed = yaml.load(value)
        }

        const result = validateBlueprintShape(parsed, blueprintTypes)
        if (result.valid) {
          setParsedPreview(result.blueprint)
          setError(null)
        }
      } catch {
        // Ignore parse errors while typing
      }
    },
    [blueprintTypes],
  )

  const handleValidateAndImport = useCallback(() => {
    const trimmed = rawInput.trim()
    if (!trimmed) {
      setError('Please paste a JSON or YAML blueprint definition.')
      return
    }

    let parsed: unknown
    const fmt = detectFormat(trimmed)

    if (fmt === 'json' || fmt === 'unknown') {
      try {
        parsed = JSON.parse(trimmed)
      } catch (e) {
        if (fmt === 'json') {
          setError(
            `Invalid JSON: ${e instanceof Error ? e.message : 'parse error'}`,
          )
          return
        }
        // Try YAML as fallback
        try {
          parsed = yaml.load(trimmed)
        } catch (yamlErr) {
          setError(
            `Could not parse as JSON or YAML: ${yamlErr instanceof Error ? yamlErr.message : 'parse error'}`,
          )
          return
        }
      }
    } else {
      try {
        parsed = yaml.load(trimmed)
      } catch (e) {
        setError(
          `Invalid YAML: ${e instanceof Error ? e.message : 'parse error'}`,
        )
        return
      }
    }

    const result = validateBlueprintShape(parsed, blueprintTypes)
    if (!result.valid) {
      setError(result.error)
      return
    }

    onImport(result.blueprint)
  }, [rawInput, blueprintTypes, onImport])

  const formatIcon =
    detectedFormat === 'json' ? (
      <FileJson className="h-3.5 w-3.5" />
    ) : detectedFormat === 'yaml' ? (
      <FileText className="h-3.5 w-3.5" />
    ) : null

  return (
    <Dialog onOpenChange={(open) => !open && handleClose()} open={isOpen}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import Blueprint</DialogTitle>
          <DialogDescription>
            Paste a JSON or YAML blueprint definition below. Required fields:{' '}
            <code className="rounded bg-secondary px-1 py-0.5 text-xs">
              name
            </code>
            ,{' '}
            <code className="rounded bg-secondary px-1 py-0.5 text-xs">
              json_schema
            </code>
            , and either{' '}
            <code className="rounded bg-secondary px-1 py-0.5 text-xs">
              type
            </code>{' '}
            (node) or{' '}
            <code className="rounded bg-secondary px-1 py-0.5 text-xs">
              source
            </code>
            /
            <code className="rounded bg-secondary px-1 py-0.5 text-xs">
              target
            </code>
            /
            <code className="rounded bg-secondary px-1 py-0.5 text-xs">
              edge
            </code>{' '}
            (relationship)
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 p-6">
          {/* Format indicator */}
          {detectedFormat !== 'unknown' && rawInput.trim() && (
            <div className="flex items-center gap-1.5">
              {formatIcon}
              <span className="text-xs text-tertiary">
                Detected format: {detectedFormat.toUpperCase()}
              </span>
              {parsedPreview && (
                <span className="ml-2 inline-flex items-center gap-1 text-xs text-green-600">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500" />
                  Valid
                </span>
              )}
            </div>
          )}

          {/* Input area */}
          <textarea
            className={`w-full resize-y rounded-md border border-input bg-secondary px-4 py-3 font-mono text-sm leading-relaxed text-primary placeholder:text-muted-foreground ${error ? 'border-danger' : ''}`}
            onChange={(e) => handleInputChange(e.target.value)}
            placeholder={`{
  "name": "AWS Metadata",
  "type": "Environment",
  "description": "AWS-specific environment properties",
  "json_schema": {
    "type": "object",
    "properties": {
      "aws_region": {
        "type": "string",
        "description": "AWS region"
      }
    },
    "required": ["aws_region"]
  }
}`}
            rows={14}
            spellCheck={false}
            value={rawInput}
          />

          {/* Validation error display */}
          {error && (
            <div className="flex items-start gap-2.5 rounded-lg border border-danger bg-danger px-3 py-2.5 text-danger">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span className="text-sm">{error}</span>
            </div>
          )}

          {/* API error display */}
          {apiError && !error && (
            <div className="flex items-start gap-2.5 rounded-lg border border-danger bg-danger px-3 py-2.5 text-danger">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <div className="text-sm">
                <div className="font-medium">Failed to import blueprint</div>
                <div className="mt-1">
                  {apiError?.response?.data?.detail ||
                    apiError?.response?.data?.message ||
                    apiError?.message ||
                    `Server error (${apiError?.response?.status || 'unknown'})`}
                </div>
              </div>
            </div>
          )}

          {/* Preview */}
          {parsedPreview && (
            <div className="rounded-lg border border-input bg-secondary px-3 py-2.5">
              <div className="mb-1.5 text-xs font-medium text-tertiary">
                Preview
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <div>
                  <span className="text-tertiary">Name: </span>
                  <span className="text-primary">{parsedPreview.name}</span>
                </div>
                <div>
                  <span className="text-tertiary">
                    {parsedPreview.kind === 'relationship'
                      ? 'Edge:'
                      : 'Type:'}{' '}
                  </span>
                  <span className="text-primary">
                    {parsedPreview.kind === 'relationship'
                      ? `${parsedPreview.source} → ${parsedPreview.target} (${parsedPreview.edge})`
                      : parsedPreview.type}
                  </span>
                </div>
                {parsedPreview.slug && (
                  <div>
                    <span className="text-tertiary">Slug: </span>
                    <span className="font-mono text-primary">
                      {parsedPreview.slug}
                    </span>
                  </div>
                )}
                {parsedPreview.description && (
                  <div className="col-span-2">
                    <span className="text-tertiary">Description: </span>
                    <span className="text-primary">
                      {parsedPreview.description}
                    </span>
                  </div>
                )}
                <div>
                  <span className="text-tertiary">Properties: </span>
                  <span className="text-primary">
                    {
                      Object.keys(
                        ((parsedPreview.json_schema as Record<string, unknown>)
                          .properties as Record<string, unknown>) || {},
                      ).length
                    }
                  </span>
                </div>
                {parsedPreview.filter &&
                  (parsedPreview.filter.project_type?.length > 0 ||
                    parsedPreview.filter.environment?.length > 0) && (
                    <div className="col-span-2">
                      <span className="text-tertiary">Filter: </span>
                      <span className="text-primary">
                        {[
                          parsedPreview.filter.project_type?.length
                            ? `${parsedPreview.filter.project_type.length} project types`
                            : '',
                          parsedPreview.filter.environment?.length
                            ? `${parsedPreview.filter.environment.length} environments`
                            : '',
                        ]
                          .filter(Boolean)
                          .join(', ')}
                      </span>
                    </div>
                  )}
              </div>
            </div>
          )}
        </div>

        <ImportDialogFooter
          hasInput={!!rawInput.trim()}
          isLoading={isLoading}
          onClose={handleClose}
          onImport={handleValidateAndImport}
        />
      </DialogContent>
    </Dialog>
  )
}

function validateBlueprintShape(
  data: unknown,
  blueprintTypes: string[],
):
  | { blueprint: BlueprintCreate; valid: true }
  | { error: string; valid: false } {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return {
      error: 'Input must be a JSON/YAML object, not an array or primitive.',
      valid: false,
    }
  }

  const obj = data as Record<string, unknown>

  // Check required fields
  for (const field of REQUIRED_FIELDS) {
    if (!(field in obj) || obj[field] === undefined || obj[field] === null) {
      return { error: `Missing required field: "${field}".`, valid: false }
    }
  }

  // Validate name
  if (typeof obj.name !== 'string' || !obj.name.trim()) {
    return { error: '"name" must be a non-empty string.', valid: false }
  }

  // Validate kind + type/relationship fields
  const bpKind = (obj.kind as string) || 'node'
  if (bpKind !== 'node' && bpKind !== 'relationship') {
    return {
      error: `"kind" must be one of: node, relationship. Got "${bpKind}".`,
      valid: false,
    }
  }
  if (bpKind === 'relationship') {
    for (const f of ['source', 'target', 'edge'] as const) {
      if (typeof obj[f] !== 'string' || !(obj[f] as string).trim()) {
        return {
          error: `"${f}" is required for relationship blueprints.`,
          valid: false,
        }
      }
    }
  } else {
    const typesToCheck =
      blueprintTypes.length > 0 ? blueprintTypes : Array.from(VALID_TYPES)
    if (typeof obj.type !== 'string' || !typesToCheck.includes(obj.type)) {
      return {
        error: `"type" must be one of: ${typesToCheck.join(', ')}. Got "${String(obj.type)}".`,
        valid: false,
      }
    }
  }

  // Validate slug if present
  if (obj.slug !== undefined && obj.slug !== null) {
    if (typeof obj.slug !== 'string') {
      return { error: '"slug" must be a string.', valid: false }
    }
    if (!/^[a-z0-9-]+$/.test(obj.slug)) {
      return {
        error:
          '"slug" must contain only lowercase letters, numbers, and hyphens.',
        valid: false,
      }
    }
  }

  // Validate json_schema
  let jsonSchema: Record<string, unknown>
  if (typeof obj.json_schema === 'string') {
    try {
      jsonSchema = JSON.parse(obj.json_schema)
    } catch {
      return {
        error: '"json_schema" is a string but not valid JSON.',
        valid: false,
      }
    }
  } else if (
    typeof obj.json_schema === 'object' &&
    !Array.isArray(obj.json_schema)
  ) {
    jsonSchema = obj.json_schema as Record<string, unknown>
  } else {
    return {
      error: '"json_schema" must be a JSON object or a JSON string.',
      valid: false,
    }
  }

  // Validate it's a valid JSON Schema
  const isValidSchema = ajv.validateSchema(jsonSchema)
  if (!isValidSchema) {
    return { error: '"json_schema" is not a valid JSON Schema.', valid: false }
  }

  // Validate optional fields
  if (obj.enabled !== undefined && typeof obj.enabled !== 'boolean') {
    return { error: '"enabled" must be a boolean.', valid: false }
  }

  if (obj.priority !== undefined && typeof obj.priority !== 'number') {
    return { error: '"priority" must be a number.', valid: false }
  }

  // Validate and normalize filter
  let parsedFilter: BlueprintFilter | null = null
  if (obj.filter !== undefined && obj.filter !== null) {
    if (typeof obj.filter !== 'object' || Array.isArray(obj.filter)) {
      return { error: '"filter" must be an object or null.', valid: false }
    }
    const f = obj.filter as Record<string, unknown>
    // Validate known keys
    const allowedKeys = new Set(['environment', 'project_type'])
    for (const key of Object.keys(f)) {
      if (!allowedKeys.has(key)) {
        return {
          error: `Unknown filter key: "${key}". Allowed: project_type, environment.`,
          valid: false,
        }
      }
      if (!Array.isArray(f[key])) {
        return {
          error: `filter.${key} must be an array of strings.`,
          valid: false,
        }
      }
      if (!(f[key] as unknown[]).every((v) => typeof v === 'string')) {
        return {
          error: `filter.${key} must contain only strings.`,
          valid: false,
        }
      }
    }
    parsedFilter = {
      environment: (f.environment as string[]) || [],
      project_type: (f.project_type as string[]) || [],
    }
  }

  if (
    obj.description !== undefined &&
    obj.description !== null &&
    typeof obj.description !== 'string'
  ) {
    return { error: '"description" must be a string or null.', valid: false }
  }

  const blueprint: BlueprintCreate = {
    kind: bpKind as 'node' | 'relationship',
    name: (obj.name as string).trim(),
    ...(bpKind === 'relationship'
      ? {
          edge: (obj.edge as string).trim(),
          source: (obj.source as string).trim(),
          target: (obj.target as string).trim(),
          type: null,
        }
      : { type: obj.type as string }),
    json_schema: jsonSchema,
    ...(obj.slug ? { slug: obj.slug as string } : {}),
    ...(obj.description !== undefined
      ? { description: obj.description as null | string }
      : {}),
    ...(obj.enabled !== undefined ? { enabled: obj.enabled as boolean } : {}),
    ...(obj.priority !== undefined ? { priority: obj.priority as number } : {}),
    ...(parsedFilter ? { filter: parsedFilter } : {}),
  }

  return { blueprint, valid: true }
}

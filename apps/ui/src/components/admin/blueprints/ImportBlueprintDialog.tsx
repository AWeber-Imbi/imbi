import { useState, useCallback, useEffect } from 'react'
import { Upload, AlertCircle, FileJson, FileText } from 'lucide-react'
import yaml from 'js-yaml'
import Ajv from 'ajv'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import type { BlueprintCreate, BlueprintFilter } from '@/types'

const ajv = new Ajv()

interface ImportBlueprintDialogProps {
  isOpen: boolean
  onClose: () => void
  onImport: (blueprint: BlueprintCreate) => void
  blueprintTypes: string[]
  isLoading?: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  apiError?: any
}

type DetectedFormat = 'json' | 'yaml' | 'unknown'

const VALID_TYPES = new Set(['Team', 'Environment', 'ProjectType', 'Project'])

const REQUIRED_FIELDS = ['name', 'json_schema'] as const

function detectFormat(input: string): DetectedFormat {
  const trimmed = input.trim()
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json'
  if (
    trimmed.includes(':') ||
    trimmed.includes(':\n') ||
    trimmed.startsWith('---')
  )
    return 'yaml'
  return 'unknown'
}

function validateBlueprintShape(
  data: unknown,
  blueprintTypes: string[],
):
  | { valid: true; blueprint: BlueprintCreate }
  | { valid: false; error: string } {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return {
      valid: false,
      error: 'Input must be a JSON/YAML object, not an array or primitive.',
    }
  }

  const obj = data as Record<string, unknown>

  // Check required fields
  for (const field of REQUIRED_FIELDS) {
    if (!(field in obj) || obj[field] === undefined || obj[field] === null) {
      return { valid: false, error: `Missing required field: "${field}".` }
    }
  }

  // Validate name
  if (typeof obj.name !== 'string' || !obj.name.trim()) {
    return { valid: false, error: '"name" must be a non-empty string.' }
  }

  // Validate kind + type/relationship fields
  const bpKind = (obj.kind as string) || 'node'
  if (bpKind !== 'node' && bpKind !== 'relationship') {
    return {
      valid: false,
      error: `"kind" must be one of: node, relationship. Got "${bpKind}".`,
    }
  }
  if (bpKind === 'relationship') {
    for (const f of ['source', 'target', 'edge'] as const) {
      if (typeof obj[f] !== 'string' || !(obj[f] as string).trim()) {
        return {
          valid: false,
          error: `"${f}" is required for relationship blueprints.`,
        }
      }
    }
  } else {
    const typesToCheck =
      blueprintTypes.length > 0 ? blueprintTypes : Array.from(VALID_TYPES)
    if (typeof obj.type !== 'string' || !typesToCheck.includes(obj.type)) {
      return {
        valid: false,
        error: `"type" must be one of: ${typesToCheck.join(', ')}. Got "${String(obj.type)}".`,
      }
    }
  }

  // Validate slug if present
  if (obj.slug !== undefined && obj.slug !== null) {
    if (typeof obj.slug !== 'string') {
      return { valid: false, error: '"slug" must be a string.' }
    }
    if (!/^[a-z0-9-]+$/.test(obj.slug)) {
      return {
        valid: false,
        error:
          '"slug" must contain only lowercase letters, numbers, and hyphens.',
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
        valid: false,
        error: '"json_schema" is a string but not valid JSON.',
      }
    }
  } else if (
    typeof obj.json_schema === 'object' &&
    !Array.isArray(obj.json_schema)
  ) {
    jsonSchema = obj.json_schema as Record<string, unknown>
  } else {
    return {
      valid: false,
      error: '"json_schema" must be a JSON object or a JSON string.',
    }
  }

  // Validate it's a valid JSON Schema
  const isValidSchema = ajv.validateSchema(jsonSchema)
  if (!isValidSchema) {
    return { valid: false, error: '"json_schema" is not a valid JSON Schema.' }
  }

  // Validate optional fields
  if (obj.enabled !== undefined && typeof obj.enabled !== 'boolean') {
    return { valid: false, error: '"enabled" must be a boolean.' }
  }

  if (obj.priority !== undefined && typeof obj.priority !== 'number') {
    return { valid: false, error: '"priority" must be a number.' }
  }

  // Validate and normalize filter
  let parsedFilter: BlueprintFilter | null = null
  if (obj.filter !== undefined && obj.filter !== null) {
    if (typeof obj.filter !== 'object' || Array.isArray(obj.filter)) {
      return { valid: false, error: '"filter" must be an object or null.' }
    }
    const f = obj.filter as Record<string, unknown>
    // Validate known keys
    const allowedKeys = new Set(['project_type', 'environment'])
    for (const key of Object.keys(f)) {
      if (!allowedKeys.has(key)) {
        return {
          valid: false,
          error: `Unknown filter key: "${key}". Allowed: project_type, environment.`,
        }
      }
      if (!Array.isArray(f[key])) {
        return {
          valid: false,
          error: `filter.${key} must be an array of strings.`,
        }
      }
      if (!(f[key] as unknown[]).every((v) => typeof v === 'string')) {
        return {
          valid: false,
          error: `filter.${key} must contain only strings.`,
        }
      }
    }
    parsedFilter = {
      project_type: (f.project_type as string[]) || [],
      environment: (f.environment as string[]) || [],
    }
  }

  if (
    obj.description !== undefined &&
    obj.description !== null &&
    typeof obj.description !== 'string'
  ) {
    return { valid: false, error: '"description" must be a string or null.' }
  }

  const blueprint: BlueprintCreate = {
    name: (obj.name as string).trim(),
    kind: bpKind as 'node' | 'relationship',
    ...(bpKind === 'relationship'
      ? {
          type: null,
          source: (obj.source as string).trim(),
          target: (obj.target as string).trim(),
          edge: (obj.edge as string).trim(),
        }
      : { type: obj.type as string }),
    json_schema: jsonSchema,
    ...(obj.slug ? { slug: obj.slug as string } : {}),
    ...(obj.description !== undefined
      ? { description: obj.description as string | null }
      : {}),
    ...(obj.enabled !== undefined ? { enabled: obj.enabled as boolean } : {}),
    ...(obj.priority !== undefined ? { priority: obj.priority as number } : {}),
    ...(parsedFilter ? { filter: parsedFilter } : {}),
  }

  return { valid: true, blueprint }
}

export function ImportBlueprintDialog({
  isOpen,
  onClose,
  onImport,
  blueprintTypes,
  isLoading = false,
  apiError,
}: ImportBlueprintDialogProps) {
  const [rawInput, setRawInput] = useState('')
  const [error, setError] = useState<string | null>(null)
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
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-primary">Import Blueprint</DialogTitle>
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

        <div className="space-y-4">
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
            value={rawInput}
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
            className={`w-full resize-y rounded-md border border-input bg-secondary px-4 py-3 font-mono text-sm leading-relaxed text-primary placeholder:text-muted-foreground ${error ? 'border-danger' : ''}`}
          />

          {/* Validation error display */}
          {error && (
            <div
              className={`flex items-start gap-2.5 rounded-lg border border-danger bg-danger px-3 py-2.5 text-danger`}
            >
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span className="text-sm">{error}</span>
            </div>
          )}

          {/* API error display */}
          {apiError && !error && (
            <div
              className={`flex items-start gap-2.5 rounded-lg border border-danger bg-danger px-3 py-2.5 text-danger`}
            >
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
            <div
              className={`rounded-lg border border-input bg-secondary px-3 py-2.5`}
            >
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

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button
            onClick={handleValidateAndImport}
            disabled={isLoading || !rawInput.trim()}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            <Upload className="mr-2 h-4 w-4" />
            {isLoading ? 'Importing...' : 'Import'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

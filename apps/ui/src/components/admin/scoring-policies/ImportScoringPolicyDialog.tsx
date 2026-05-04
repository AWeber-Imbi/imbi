import { useCallback, useEffect, useState } from 'react'

import yaml from 'js-yaml'
import { AlertCircle, FileJson, FileText, Upload } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { ScoringPolicyCreate } from '@/types'

type DetectedFormat = 'json' | 'unknown' | 'yaml'

interface ImportScoringPolicyDialogProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  apiError?: any
  isLoading?: boolean
  isOpen: boolean
  onClose: () => void
  onImport: (policy: ScoringPolicyCreate) => void
}

const REQUIRED_FIELDS = ['name', 'slug', 'attribute_name', 'weight'] as const

export function ImportScoringPolicyDialog({
  apiError,
  isLoading = false,
  isOpen,
  onClose,
  onImport,
}: ImportScoringPolicyDialogProps) {
  const [rawInput, setRawInput] = useState('')
  const [error, setError] = useState<null | string>(null)
  const [parsedPreview, setParsedPreview] =
    useState<null | ScoringPolicyCreate>(null)
  const [detectedFormat, setDetectedFormat] =
    useState<DetectedFormat>('unknown')
  const [showApiError, setShowApiError] = useState(false)

  const reset = useCallback(() => {
    setRawInput('')
    setError(null)
    setParsedPreview(null)
    setDetectedFormat('unknown')
    setShowApiError(false)
  }, [])

  useEffect(() => {
    if (isOpen) reset()
  }, [isOpen, reset])

  const handleClose = useCallback(() => {
    reset()
    onClose()
  }, [reset, onClose])

  const handleInputChange = useCallback((value: string) => {
    setRawInput(value)
    setError(null)
    setShowApiError(false)
    setParsedPreview(null)

    if (!value.trim()) {
      setDetectedFormat('unknown')
      return
    }

    const fmt = detectFormat(value)
    setDetectedFormat(fmt)

    try {
      let parsed: unknown
      let jsonFailed = false
      if (fmt === 'json' || fmt === 'unknown') {
        try {
          parsed = JSON.parse(value)
        } catch {
          jsonFailed = true
        }
      }
      if (jsonFailed || fmt === 'yaml') {
        try {
          parsed = yaml.load(value)
        } catch {
          return
        }
      }

      const result = validatePolicyShape(parsed)
      if (result.valid) {
        setParsedPreview(result.policy)
        setError(null)
      }
    } catch {
      // ignore parse errors while typing
    }
  }, [])

  const handleValidateAndImport = useCallback(() => {
    const trimmed = rawInput.trim()
    if (!trimmed) {
      setError('Please paste a JSON or YAML scoring policy definition.')
      return
    }

    let parsed: unknown
    const fmt = detectFormat(trimmed)
    let jsonParseError: Error | null = null

    if (fmt === 'json' || fmt === 'unknown') {
      try {
        parsed = JSON.parse(trimmed)
      } catch (e) {
        jsonParseError = e instanceof Error ? e : new Error('parse error')
      }
    }

    if (jsonParseError !== null || fmt === 'yaml') {
      try {
        parsed = yaml.load(trimmed)
      } catch (yamlErr) {
        if (jsonParseError !== null) {
          setError(
            `Could not parse as JSON or YAML: ${yamlErr instanceof Error ? yamlErr.message : 'parse error'}`,
          )
        } else {
          setError(
            `Invalid YAML: ${yamlErr instanceof Error ? yamlErr.message : 'parse error'}`,
          )
        }
        return
      }
    }

    const result = validatePolicyShape(parsed)
    if (!result.valid) {
      setError(result.error)
      return
    }

    setShowApiError(true)
    onImport(result.policy)
  }, [rawInput, onImport])

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
          <DialogTitle className="text-primary">
            Import Scoring Policy
          </DialogTitle>
          <DialogDescription>
            Paste a JSON or YAML scoring policy definition below. Required
            fields:{' '}
            {REQUIRED_FIELDS.map((f, i) => (
              <span key={f}>
                <code className="rounded bg-secondary px-1 py-0.5 text-xs">
                  {f}
                </code>
                {i < REQUIRED_FIELDS.length - 1 ? ', ' : ''}
              </span>
            ))}{' '}
            and at least one of{' '}
            <code className="rounded bg-secondary px-1 py-0.5 text-xs">
              value_score_map
            </code>{' '}
            or{' '}
            <code className="rounded bg-secondary px-1 py-0.5 text-xs">
              range_score_map
            </code>
            .
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
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

          <textarea
            className={`w-full resize-y rounded-md border border-input bg-secondary px-4 py-3 font-mono text-sm leading-relaxed text-primary placeholder:text-muted-foreground ${error ? 'border-danger' : ''}`}
            onChange={(e) => handleInputChange(e.target.value)}
            placeholder={`{
  "name": "Test Coverage",
  "slug": "test-coverage",
  "attribute_name": "test_coverage",
  "weight": 50,
  "priority": 0,
  "enabled": true,
  "targets": [],
  "value_score_map": {
    "passing": 100,
    "failing": 0
  }
}`}
            rows={14}
            spellCheck={false}
            value={rawInput}
          />

          {error && (
            <div className="flex items-start gap-2.5 rounded-lg border border-danger bg-danger px-3 py-2.5 text-danger">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span className="text-sm">{error}</span>
            </div>
          )}

          {apiError && showApiError && !error && (
            <div className="flex items-start gap-2.5 rounded-lg border border-danger bg-danger px-3 py-2.5 text-danger">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <div className="text-sm">
                <div className="font-medium">
                  Failed to import scoring policy
                </div>
                <div className="mt-1">
                  {apiError?.response?.data?.detail ||
                    apiError?.response?.data?.message ||
                    apiError?.message ||
                    `Server error (${apiError?.response?.status || 'unknown'})`}
                </div>
              </div>
            </div>
          )}

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
                  <span className="text-tertiary">Slug: </span>
                  <span className="font-mono text-primary">
                    {parsedPreview.slug}
                  </span>
                </div>
                <div>
                  <span className="text-tertiary">Attribute: </span>
                  <code className="rounded bg-card px-1 py-0.5 text-xs text-primary">
                    {parsedPreview.attribute_name}
                  </code>
                </div>
                <div>
                  <span className="text-tertiary">Weight: </span>
                  <span className="text-primary">{parsedPreview.weight}</span>
                </div>
                <div>
                  <span className="text-tertiary">Map type: </span>
                  <span className="text-primary">
                    {parsedPreview.range_score_map ? 'Range' : 'Value'}
                  </span>
                </div>
                {(parsedPreview.targets ?? []).length > 0 && (
                  <div className="col-span-2">
                    <span className="text-tertiary">Targets: </span>
                    <span className="text-primary">
                      {parsedPreview.targets.join(', ')}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button disabled={isLoading} onClick={handleClose} variant="outline">
            Cancel
          </Button>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={isLoading || !rawInput.trim()}
            onClick={handleValidateAndImport}
          >
            <Upload className="mr-2 h-4 w-4" />
            {isLoading ? 'Importing...' : 'Import'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function detectFormat(input: string): DetectedFormat {
  const trimmed = input.trim()
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json'
  if (
    trimmed.includes(': ') ||
    trimmed.includes(':\n') ||
    trimmed.startsWith('---')
  )
    return 'yaml'
  return 'unknown'
}

function validatePolicyShape(
  data: unknown,
):
  | { error: string; valid: false }
  | { policy: ScoringPolicyCreate; valid: true } {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return { error: 'Input must be a JSON/YAML object.', valid: false }
  }

  const obj = data as Record<string, unknown>

  for (const field of REQUIRED_FIELDS) {
    if (obj[field] === undefined || obj[field] === null) {
      return { error: `Missing required field: "${field}".`, valid: false }
    }
  }

  if (typeof obj.name !== 'string' || !obj.name.trim()) {
    return { error: '"name" must be a non-empty string.', valid: false }
  }
  if (typeof obj.slug !== 'string' || !/^[a-z0-9_-]+$/.test(obj.slug)) {
    return {
      error:
        '"slug" must be lowercase letters, numbers, hyphens, or underscores.',
      valid: false,
    }
  }
  if (typeof obj.attribute_name !== 'string' || !obj.attribute_name.trim()) {
    return {
      error: '"attribute_name" must be a non-empty string.',
      valid: false,
    }
  }

  if (
    typeof obj.weight !== 'number' ||
    !Number.isFinite(obj.weight) ||
    obj.weight < 0 ||
    obj.weight > 100
  ) {
    return {
      error: '"weight" must be a number between 0 and 100.',
      valid: false,
    }
  }
  const weight = obj.weight

  const hasValueMap =
    obj.value_score_map !== null &&
    obj.value_score_map !== undefined &&
    typeof obj.value_score_map === 'object' &&
    !Array.isArray(obj.value_score_map) &&
    Object.keys(obj.value_score_map as object).length > 0
  const hasRangeMap =
    obj.range_score_map !== null &&
    obj.range_score_map !== undefined &&
    typeof obj.range_score_map === 'object' &&
    !Array.isArray(obj.range_score_map) &&
    Object.keys(obj.range_score_map as object).length > 0

  if (!hasValueMap && !hasRangeMap) {
    return {
      error:
        'At least one of "value_score_map" or "range_score_map" must have entries.',
      valid: false,
    }
  }

  if (
    obj.targets !== undefined &&
    obj.targets !== null &&
    (!Array.isArray(obj.targets) ||
      !(obj.targets as unknown[]).every((v) => typeof v === 'string'))
  ) {
    return { error: '"targets" must be an array of strings.', valid: false }
  }

  if (obj.enabled !== undefined && typeof obj.enabled !== 'boolean') {
    return { error: '"enabled" must be a boolean.', valid: false }
  }

  if (
    obj.priority !== undefined &&
    (typeof obj.priority !== 'number' || !Number.isFinite(obj.priority))
  ) {
    return { error: '"priority" must be a number.', valid: false }
  }

  const hasOnlyNumericValues = (map: unknown): map is Record<string, number> =>
    !!map &&
    typeof map === 'object' &&
    !Array.isArray(map) &&
    Object.values(map as Record<string, unknown>).every(
      (v) => typeof v === 'number' && Number.isFinite(v),
    )

  if (hasValueMap && !hasOnlyNumericValues(obj.value_score_map)) {
    return {
      error: '"value_score_map" values must be numbers.',
      valid: false,
    }
  }

  if (hasRangeMap && !hasOnlyNumericValues(obj.range_score_map)) {
    return {
      error: '"range_score_map" values must be numbers.',
      valid: false,
    }
  }

  const policy: ScoringPolicyCreate = {
    attribute_name: (obj.attribute_name as string).trim(),
    description:
      typeof obj.description === 'string'
        ? obj.description.trim() || null
        : null,
    enabled: obj.enabled === undefined ? true : obj.enabled,
    name: (obj.name as string).trim(),
    priority: obj.priority === undefined ? 0 : obj.priority,
    range_score_map: hasRangeMap
      ? (obj.range_score_map as Record<string, number>)
      : null,
    slug: obj.slug as string,
    targets: Array.isArray(obj.targets) ? (obj.targets as string[]) : [],
    value_score_map: hasValueMap
      ? (obj.value_score_map as Record<string, number>)
      : null,
    weight,
  }

  return { policy, valid: true }
}

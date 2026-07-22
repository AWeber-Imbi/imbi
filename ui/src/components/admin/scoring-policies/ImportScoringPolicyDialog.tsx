import { useCallback, useEffect, useState } from 'react'

import yaml from 'js-yaml'
import { AlertCircle, FileJson, FileText } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { type DetectedFormat, detectFormat } from '@/lib/import-format'
import type {
  AgeScoringPolicyCreate,
  AnalysisResultScoringPolicyCreate,
  AttributeScoringPolicyCreate,
  Condition,
  ConditionScoringPolicyCreate,
  LinkPresenceScoringPolicyCreate,
  PresenceScoringPolicyCreate,
  ScoringPolicyCategory,
  ScoringPolicyCreate,
} from '@/types'

import { ImportDialogFooter } from '../import-dialog-shared'

interface FieldRule {
  error: string
  ok: (obj: Record<string, unknown>) => boolean
}

interface ImportScoringPolicyDialogProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  apiError?: any
  isLoading?: boolean
  isOpen: boolean
  onClose: () => void
  onImport: (policy: ScoringPolicyCreate) => void
}

interface PolicyBase {
  description: null | string
  enabled: boolean
  name: string
  priority: number
  slug: string
  targets: string[]
  weight: number
}

type PolicyResult<T> =
  | { error: string; valid: false }
  | { policy: T; valid: true }

const COMMON_REQUIRED = ['name', 'slug', 'weight'] as const

const VALID_CATEGORIES: ScoringPolicyCategory[] = [
  'attribute',
  'presence',
  'link_presence',
  'age',
  'analysis_result',
  'condition',
]

const CATEGORY_LABELS: Record<ScoringPolicyCategory, string> = {
  age: 'Age',
  analysis_result: 'Analysis Result',
  attribute: 'Attribute',
  condition: 'Condition',
  link_presence: 'Link Presence',
  presence: 'Presence',
}

const BASE_FIELD_RULES: FieldRule[] = [
  {
    error: 'Missing required fields: name, slug, weight.',
    ok: (obj) =>
      COMMON_REQUIRED.every((f) => obj[f] !== undefined && obj[f] !== null),
  },
  {
    error: '"name" must be a non-empty string.',
    ok: (obj) => typeof obj.name === 'string' && obj.name.trim().length > 0,
  },
  {
    error:
      '"slug" must be lowercase letters, numbers, hyphens, or underscores.',
    ok: (obj) => typeof obj.slug === 'string' && /^[a-z0-9_-]+$/.test(obj.slug),
  },
  {
    error: '"weight" must be a number between 0 and 100.',
    ok: (obj) => isNumberInRange(obj.weight, 0, 100),
  },
  {
    error: '"targets" must be an array of strings.',
    ok: (obj) =>
      obj.targets === undefined ||
      obj.targets === null ||
      isStringArray(obj.targets),
  },
  {
    error: '"enabled" must be a boolean.',
    ok: (obj) => obj.enabled === undefined || typeof obj.enabled === 'boolean',
  },
  {
    error: '"priority" must be a number.',
    ok: (obj) => obj.priority === undefined || isFiniteNumber(obj.priority),
  },
]

// fallow-ignore-next-line complexity
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

  // fallow-ignore-next-line complexity
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

  // fallow-ignore-next-line complexity
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
      <FileJson className="size-3.5" />
    ) : detectedFormat === 'yaml' ? (
      <FileText className="size-3.5" />
    ) : null

  return (
    <Dialog onOpenChange={(open) => !open && handleClose()} open={isOpen}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import Scoring Policy</DialogTitle>
          <DialogDescription>
            Paste a JSON or YAML scoring policy definition below. Required
            fields:{' '}
            {COMMON_REQUIRED.map((f, i) => (
              <span key={f}>
                <code className="bg-secondary rounded px-1 py-0.5 text-xs">
                  {f}
                </code>
                {i < COMMON_REQUIRED.length - 1 ? ', ' : ''}
              </span>
            ))}
            . Optional{' '}
            <code className="bg-secondary rounded px-1 py-0.5 text-xs">
              category
            </code>{' '}
            defaults to{' '}
            <code className="bg-secondary rounded px-1 py-0.5 text-xs">
              attribute
            </code>
            ; other supported values are{' '}
            <code className="bg-secondary rounded px-1 py-0.5 text-xs">
              presence
            </code>
            ,{' '}
            <code className="bg-secondary rounded px-1 py-0.5 text-xs">
              link_presence
            </code>
            ,{' '}
            <code className="bg-secondary rounded px-1 py-0.5 text-xs">
              age
            </code>
            , and{' '}
            <code className="bg-secondary rounded px-1 py-0.5 text-xs">
              analysis_result
            </code>
            .
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 p-6">
          {detectedFormat !== 'unknown' && rawInput.trim() && (
            <div className="flex items-center gap-1.5">
              {formatIcon}
              <span className="text-tertiary text-xs">
                Detected format: {detectedFormat.toUpperCase()}
              </span>
              {parsedPreview && (
                <span className="ml-2 inline-flex items-center gap-1 text-xs text-green-600">
                  <span className="inline-block size-1.5 rounded-full bg-green-500" />
                  Valid
                </span>
              )}
            </div>
          )}

          <Textarea
            className={`bg-secondary text-primary resize-y px-4 py-3 font-mono leading-relaxed ${error ? 'border-danger' : ''}`}
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
            <div className="border-danger bg-danger text-danger flex items-start gap-2.5 rounded-lg border px-3 py-2.5">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <span className="text-sm">{error}</span>
            </div>
          )}

          {apiError && showApiError && !error && (
            <div className="border-danger bg-danger text-danger flex items-start gap-2.5 rounded-lg border px-3 py-2.5">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
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
            <div className="border-input bg-secondary rounded-lg border px-3 py-2.5">
              <div className="text-tertiary mb-1.5 text-xs font-medium">
                Preview
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <div>
                  <span className="text-tertiary">Name: </span>
                  <span className="text-primary">{parsedPreview.name}</span>
                </div>
                <div>
                  <span className="text-tertiary">Slug: </span>
                  <span className="text-primary font-mono">
                    {parsedPreview.slug}
                  </span>
                </div>
                <div>
                  <span className="text-tertiary">Category: </span>
                  <span className="text-primary">
                    {CATEGORY_LABELS[parsedPreview.category]}
                  </span>
                </div>
                <div>
                  <span className="text-tertiary">
                    {parsedPreview.category === 'link_presence'
                      ? 'Link slug: '
                      : parsedPreview.category === 'analysis_result'
                        ? 'Result slug: '
                        : 'Attribute: '}
                  </span>
                  <code className="bg-card text-primary rounded px-1 py-0.5 text-xs">
                    {policySubjectKey(parsedPreview)}
                  </code>
                </div>
                <div>
                  <span className="text-tertiary">Weight: </span>
                  <span className="text-primary">{parsedPreview.weight}</span>
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

function buildBase(obj: Record<string, unknown>): PolicyBase {
  return {
    description: trimDescription(obj.description),
    enabled: (obj.enabled ?? true) as boolean,
    name: (obj.name as string).trim(),
    priority: (obj.priority ?? 0) as number,
    slug: obj.slug as string,
    targets: Array.isArray(obj.targets) ? (obj.targets as string[]) : [],
    weight: obj.weight as number,
  }
}

function checkBaseFields(obj: Record<string, unknown>): null | string {
  for (const rule of BASE_FIELD_RULES) {
    if (!rule.ok(obj)) return rule.error
  }
  return null
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isNonEmptyNumberMap(value: unknown): boolean {
  if (!isPlainObject(value)) return false
  const entries = Object.entries(value)
  return entries.length > 0 && entries.every(([, v]) => isFiniteNumber(v))
}

function isNumberInRange(
  value: unknown,
  min: number,
  max: number,
): value is number {
  return isFiniteNumber(value) && value >= min && value <= max
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string')
}

function optionalScore(
  value: unknown,
  field: string,
): { error: string; ok: false } | { ok: true; value: null | number } {
  if (value === undefined || value === null) return { ok: true, value: null }
  if (!isNumberInRange(value, 0, 100)) {
    return {
      error: `"${field}" must be a number between 0 and 100.`,
      ok: false,
    }
  }
  return { ok: true, value }
}

function policySubjectKey(policy: ScoringPolicyCreate): string {
  if (policy.category === 'link_presence') return policy.link_slug
  if (policy.category === 'analysis_result') return policy.result_slug
  if (policy.category === 'condition') return ''
  return policy.attribute_name
}

function readScoreMap(
  raw: unknown,
  field: string,
):
  | { error: string; ok: false }
  | { ok: true; value: null | Record<string, number> } {
  if (raw === undefined || raw === null) return { ok: true, value: null }
  if (!isNonEmptyNumberMap(raw)) {
    return { error: `"${field}" values must be numbers.`, ok: false }
  }
  return { ok: true, value: raw as Record<string, number> }
}

function readScorePair(
  obj: Record<string, unknown>,
):
  | { error: string; ok: false }
  | { missing: null | number; ok: true; present: null | number } {
  const present = optionalScore(obj.present_score, 'present_score')
  if (!present.ok) return { error: present.error, ok: false }
  const missing = optionalScore(obj.missing_score, 'missing_score')
  if (!missing.ok) return { error: missing.error, ok: false }
  return { missing: missing.value, ok: true, present: present.value }
}

function requireString(
  obj: Record<string, unknown>,
  field: string,
): { error: string; ok: false } | { ok: true; value: string } {
  const value = obj[field]
  if (typeof value !== 'string' || !value.trim()) {
    return { error: `"${field}" must be a non-empty string.`, ok: false }
  }
  return { ok: true, value: value.trim() }
}

function resolveCategory(
  raw: unknown,
): { error: string; ok: false } | { ok: true; value: ScoringPolicyCategory } {
  const candidate = raw ?? 'attribute'
  if (
    typeof candidate !== 'string' ||
    !VALID_CATEGORIES.includes(candidate as ScoringPolicyCategory)
  ) {
    return {
      error: `"category" must be one of: ${VALID_CATEGORIES.join(', ')}.`,
      ok: false,
    }
  }
  return { ok: true, value: candidate as ScoringPolicyCategory }
}

function trimDescription(value: unknown): null | string {
  return typeof value === 'string' ? value.trim() || null : null
}

function validateAgePolicy(
  obj: Record<string, unknown>,
  base: PolicyBase,
): PolicyResult<AgeScoringPolicyCreate> {
  const attrCheck = requireString(obj, 'attribute_name')
  if (!attrCheck.ok) return { error: attrCheck.error, valid: false }
  const ageCheck = validateAgeScoreMap(obj.age_score_map)
  if (!ageCheck.ok) return { error: ageCheck.error, valid: false }
  return {
    policy: {
      ...base,
      age_score_map: obj.age_score_map as Record<string, number>,
      attribute_name: attrCheck.value,
      category: 'age',
    },
    valid: true,
  }
}

function validateAgeScoreMap(
  raw: unknown,
): { error: string; ok: false } | { ok: true } {
  if (!isNonEmptyNumberMap(raw)) {
    return {
      error:
        '"age_score_map" must be a non-empty object whose values are numbers.',
      ok: false,
    }
  }
  const invalid = Object.keys(raw as object).find(
    (key) => !/^(>=|>|<=|<|==)\s*\d+(?:\.\d+)?\s*[smhdw]$/.test(key),
  )
  if (invalid !== undefined) {
    return {
      error: `"age_score_map" key ${JSON.stringify(invalid)} is not a valid threshold (e.g. ">30d", "<=7d").`,
      ok: false,
    }
  }
  return { ok: true }
}

// fallow-ignore-next-line complexity
function validateAnalysisResultPolicy(
  obj: Record<string, unknown>,
  base: PolicyBase,
): PolicyResult<AnalysisResultScoringPolicyCreate> {
  const slugCheck = requireString(obj, 'result_slug')
  if (!slugCheck.ok) return { error: slugCheck.error, valid: false }
  const rawMap = obj.status_score_map
  let status_score_map: null | Record<'fail' | 'pass' | 'warn', number> = null
  if (rawMap !== undefined && rawMap !== null) {
    if (!isNonEmptyNumberMap(rawMap)) {
      return {
        error: '"status_score_map" values must be numbers.',
        valid: false,
      }
    }
    const required = ['fail', 'pass', 'warn'] as const
    const allowed = new Set<string>(required)
    const keys = Object.keys(rawMap as object)
    const invalid = keys.find((k) => !allowed.has(k))
    if (invalid) {
      return {
        error: `"status_score_map" key ${JSON.stringify(invalid)} must be "pass", "warn", or "fail".`,
        valid: false,
      }
    }
    const missing = required.filter(
      (k) => !Object.prototype.hasOwnProperty.call(rawMap, k),
    )
    if (missing.length > 0) {
      return {
        error: `"status_score_map" is missing required key(s): ${missing.join(', ')}.`,
        valid: false,
      }
    }
    status_score_map = rawMap as Record<'fail' | 'pass' | 'warn', number>
  }
  return {
    policy: {
      ...base,
      category: 'analysis_result',
      result_slug: slugCheck.value,
      status_score_map,
    },
    valid: true,
  }
}

// fallow-ignore-next-line complexity
function validateAttributeMaps(obj: Record<string, unknown>):
  | { error: string; ok: false }
  | {
      ok: true
      range: null | Record<string, number>
      value: null | Record<string, number>
    } {
  const valueCheck = readScoreMap(obj.value_score_map, 'value_score_map')
  if (!valueCheck.ok) return { error: valueCheck.error, ok: false }
  const rangeCheck = readScoreMap(obj.range_score_map, 'range_score_map')
  if (!rangeCheck.ok) return { error: rangeCheck.error, ok: false }
  if (!valueCheck.value && !rangeCheck.value) {
    return {
      error:
        'At least one of "value_score_map" or "range_score_map" must have entries.',
      ok: false,
    }
  }
  return { ok: true, range: rangeCheck.value, value: valueCheck.value }
}

function validateAttributePolicy(
  obj: Record<string, unknown>,
  base: PolicyBase,
): PolicyResult<AttributeScoringPolicyCreate> {
  const attrCheck = requireString(obj, 'attribute_name')
  if (!attrCheck.ok) return { error: attrCheck.error, valid: false }
  const maps = validateAttributeMaps(obj)
  if (!maps.ok) return { error: maps.error, valid: false }
  return {
    policy: {
      ...base,
      attribute_name: attrCheck.value,
      category: 'attribute',
      range_score_map: maps.range,
      value_score_map: maps.value,
    },
    valid: true,
  }
}

function validateBaseShape(obj: Record<string, unknown>):
  | {
      base: PolicyBase
      category: ScoringPolicyCategory
      obj: Record<string, unknown>
      valid: true
    }
  | { error: string; valid: false } {
  const fieldError = checkBaseFields(obj)
  if (fieldError) return { error: fieldError, valid: false }
  const categoryCheck = resolveCategory(obj.category)
  if (!categoryCheck.ok) return { error: categoryCheck.error, valid: false }
  return {
    base: buildBase(obj),
    category: categoryCheck.value,
    obj,
    valid: true,
  }
}

const CONDITION_OPS = new Set([
  'absent',
  'eq',
  'ge',
  'gt',
  'le',
  'lt',
  'ne',
  'present',
])

const RELATIONSHIP_QUANTIFIERS = new Set(['all', 'any', 'none'])

function isValidAttributeNode(node: Record<string, unknown>): boolean {
  return (
    typeof node.attribute === 'string' &&
    node.attribute.length > 0 &&
    CONDITION_OPS.has(node.op as string)
  )
}

function isValidCombinator(
  node: Record<string, unknown>,
  key: 'all' | 'any',
): boolean {
  const list = node[key]
  return (
    Array.isArray(list) && list.length > 0 && list.every(isValidConditionNode)
  )
}

// fallow-ignore-next-line complexity
function isValidConditionNode(node: unknown): boolean {
  if (!isPlainObject(node)) return false
  if ('all' in node) return isValidCombinator(node, 'all')
  if ('any' in node) return isValidCombinator(node, 'any')
  if ('not' in node) return isValidConditionNode(node.not)
  if ('relationship' in node) return isValidRelationshipNode(node)
  if ('attribute' in node) return isValidAttributeNode(node)
  return false
}

// fallow-ignore-next-line complexity
function isValidRelationshipNode(node: Record<string, unknown>): boolean {
  const r = node.relationship
  if (!isPlainObject(r)) return false
  return (
    r.direction === 'outgoing' &&
    r.edge === 'DEPENDS_ON' &&
    RELATIONSHIP_QUANTIFIERS.has(r.quantifier as string) &&
    isValidConditionNode(r.where)
  )
}

// fallow-ignore-next-line complexity
function validateConditionPolicy(
  obj: Record<string, unknown>,
  base: PolicyBase,
): PolicyResult<ConditionScoringPolicyCreate> {
  if (!isPlainObject(obj.condition)) {
    return { error: '"condition" must be an object.', valid: false }
  }
  if (!isValidConditionNode(obj.condition)) {
    return { error: '"condition" is not a valid condition tree.', valid: false }
  }
  const trueScore = optionalScore(obj.true_score, 'true_score')
  if (!trueScore.ok) return { error: trueScore.error, valid: false }
  const falseScore = optionalScore(obj.false_score, 'false_score')
  if (!falseScore.ok) return { error: falseScore.error, valid: false }
  return {
    policy: {
      ...base,
      category: 'condition',
      condition: obj.condition as unknown as Condition,
      false_score: falseScore.value ?? 0,
      true_score: trueScore.value ?? 100,
    },
    valid: true,
  }
}

function validateLinkPresencePolicy(
  obj: Record<string, unknown>,
  base: PolicyBase,
): PolicyResult<LinkPresenceScoringPolicyCreate> {
  const linkCheck = requireString(obj, 'link_slug')
  if (!linkCheck.ok) return { error: linkCheck.error, valid: false }
  const scores = readScorePair(obj)
  if (!scores.ok) return { error: scores.error, valid: false }
  return {
    policy: {
      ...base,
      category: 'link_presence',
      link_slug: linkCheck.value,
      missing_score: scores.missing,
      present_score: scores.present,
    },
    valid: true,
  }
}

const CATEGORY_VALIDATORS: Record<
  ScoringPolicyCategory,
  (
    obj: Record<string, unknown>,
    base: PolicyBase,
  ) => PolicyResult<ScoringPolicyCreate>
> = {
  age: validateAgePolicy,
  analysis_result: validateAnalysisResultPolicy,
  attribute: validateAttributePolicy,
  condition: validateConditionPolicy,
  link_presence: validateLinkPresencePolicy,
  presence: validatePresencePolicy,
}

function validatePolicyShape(data: unknown): PolicyResult<ScoringPolicyCreate> {
  if (!isPlainObject(data)) {
    return { error: 'Input must be a JSON/YAML object.', valid: false }
  }
  const baseResult = validateBaseShape(data)
  if (!baseResult.valid) return baseResult
  return CATEGORY_VALIDATORS[baseResult.category](
    baseResult.obj,
    baseResult.base,
  )
}

function validatePresencePolicy(
  obj: Record<string, unknown>,
  base: PolicyBase,
): PolicyResult<PresenceScoringPolicyCreate> {
  const attrCheck = requireString(obj, 'attribute_name')
  if (!attrCheck.ok) return { error: attrCheck.error, valid: false }
  const scores = readScorePair(obj)
  if (!scores.ok) return { error: scores.error, valid: false }
  return {
    policy: {
      ...base,
      attribute_name: attrCheck.value,
      category: 'presence',
      missing_score: scores.missing,
      present_score: scores.present,
    },
    valid: true,
  }
}

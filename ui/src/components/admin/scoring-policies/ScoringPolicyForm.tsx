import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Plus, Trash2 } from 'lucide-react'

import { listLinkDefinitions, listProjectTypes } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import {
  ConditionBuilder,
  DEFAULT_CONDITION,
  normalizeCondition,
} from '@/components/admin/scoring-policies/ConditionBuilder'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import { queryKeys } from '@/lib/queryKeys'
import { slugify } from '@/lib/utils'
import type {
  Condition,
  ScoringPolicy,
  ScoringPolicyCategory,
  ScoringPolicyCreate,
} from '@/types'

type AttributeMapType = 'range' | 'value'

interface MapRow {
  id: string
  key: string
  score: string
}

const CATEGORY_LABELS: Record<ScoringPolicyCategory, string> = {
  age: 'Age',
  analysis_result: 'Analysis Result',
  attribute: 'Attribute',
  condition: 'Condition',
  link_presence: 'Link Presence',
  presence: 'Presence',
}

const CATEGORY_DESCRIPTIONS: Record<ScoringPolicyCategory, string> = {
  age: 'Score by how recently a datetime attribute changed, using the same threshold DSL as blueprint age maps (e.g. >30d, <=7d). Recomputed daily.',
  analysis_result:
    "Score based on a Project Doctor analysis result's status (pass / warn / fail). The result is identified by its plugin-emitted slug.",
  attribute:
    'Map a specific attribute value or numeric range to a score (e.g. test-coverage tiers).',
  condition:
    'Combine attribute and relationship predicates with boolean logic, then map the result to a score (e.g. penalize projects that depend on a deprecated service).',
  link_presence:
    'Penalize projects that do not have a link of a specific type (e.g. missing source-code link).',
  presence:
    'Penalize projects whose attribute is null, empty, or whitespace (e.g. empty description).',
}

interface MapEditorProps {
  addLabel: string
  disabled?: boolean
  error?: string
  keyHeader: string
  keyPlaceholder: string
  onChange: (rows: MapRow[]) => void
  rows: MapRow[]
  scoreHeader: string
}

interface ScoringPolicyFormProps {
  error?: unknown
  isLoading?: boolean
  onCancel: () => void
  onSave: (data: ScoringPolicyCreate) => void
  policy: null | ScoringPolicy
}

// fallow-ignore-next-line complexity
export function ScoringPolicyForm({
  error,
  isLoading = false,
  onCancel,
  onSave,
  policy,
}: ScoringPolicyFormProps) {
  const isEditing = policy !== null

  const initialCategory: ScoringPolicyCategory = policy?.category ?? 'attribute'

  const [category, setCategory] =
    useState<ScoringPolicyCategory>(initialCategory)
  const [name, setName] = useState(policy?.name ?? '')
  const [slug, setSlug] = useState(policy?.slug ?? '')
  const [description, setDescription] = useState(policy?.description ?? '')
  const [weight, setWeight] = useState(String(policy?.weight ?? 50))
  const [priority, setPriority] = useState(String(policy?.priority ?? 0))
  const [enabled, setEnabled] = useState(policy?.enabled ?? true)
  const [targets, setTargets] = useState<string[]>(policy?.targets ?? [])

  // Per-category state
  const [attributeName, setAttributeName] = useState(
    policy && 'attribute_name' in policy ? policy.attribute_name : '',
  )
  const [linkSlug, setLinkSlug] = useState(
    policy && policy.category === 'link_presence' ? policy.link_slug : '',
  )
  const [presentScore, setPresentScore] = useState(
    policy &&
      (policy.category === 'presence' || policy.category === 'link_presence')
      ? String(policy.present_score ?? 100)
      : '100',
  )
  const [missingScore, setMissingScore] = useState(
    policy &&
      (policy.category === 'presence' || policy.category === 'link_presence')
      ? String(policy.missing_score ?? 0)
      : '0',
  )
  const [attributeMapType, setAttributeMapType] = useState<AttributeMapType>(
    policy?.category === 'attribute' && policy.range_score_map != null
      ? 'range'
      : 'value',
  )
  const [attributeMapRows, setAttributeMapRows] = useState<MapRow[]>(() => {
    if (policy?.category === 'attribute') {
      return attributeMapType === 'range'
        ? parseMapToRows(policy.range_score_map)
        : parseMapToRows(policy.value_score_map)
    }
    return [emptyRow()]
  })
  const [ageMapRows, setAgeMapRows] = useState<MapRow[]>(() =>
    policy?.category === 'age'
      ? parseMapToRows(policy.age_score_map)
      : [
          newRow('>90d', '0'),
          newRow('>30d', '25'),
          newRow('>7d', '75'),
          newRow('<=7d', '100'),
        ],
  )
  const [resultSlug, setResultSlug] = useState(
    policy && policy.category === 'analysis_result' ? policy.result_slug : '',
  )
  const [analysisPassScore, setAnalysisPassScore] = useState(
    policy?.category === 'analysis_result'
      ? String(policy.status_score_map?.pass ?? 100)
      : '100',
  )
  const [analysisWarnScore, setAnalysisWarnScore] = useState(
    policy?.category === 'analysis_result'
      ? String(policy.status_score_map?.warn ?? 50)
      : '50',
  )
  const [analysisFailScore, setAnalysisFailScore] = useState(
    policy?.category === 'analysis_result'
      ? String(policy.status_score_map?.fail ?? 0)
      : '0',
  )
  const [condition, setCondition] = useState<Condition>(() =>
    policy?.category === 'condition'
      ? normalizeCondition(policy.condition)
      : DEFAULT_CONDITION,
  )
  const [trueScore, setTrueScore] = useState(
    policy?.category === 'condition' ? String(policy.true_score) : '100',
  )
  const [falseScore, setFalseScore] = useState(
    policy?.category === 'condition' ? String(policy.false_score) : '0',
  )

  const [errors, setErrors] = useState<Record<string, string>>({})

  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug

  const {
    data: projectTypes = [],
    isError: ptIsError,
    isLoading: ptLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listProjectTypes(orgSlug!, signal),
    queryKey: queryKeys.projectTypes(orgSlug ?? ''),
    staleTime: 5 * 60 * 1000,
  })

  const { data: linkDefinitions = [] } = useQuery({
    enabled: !!orgSlug && category === 'link_presence',
    queryFn: ({ signal }) => listLinkDefinitions(orgSlug!, signal),
    queryKey: ['linkDefinitions', orgSlug],
    staleTime: 5 * 60 * 1000,
  })

  const sortedLinkDefinitions = useMemo(
    () => [...linkDefinitions].sort((a, b) => a.name.localeCompare(b.name)),
    [linkDefinitions],
  )

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) setSlug(slugify(value))
  }

  const handleAttributeMapTypeChange = (type: AttributeMapType) => {
    setAttributeMapType(type)
    setAttributeMapRows([emptyRow()])
  }

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {
      ...validateIdentity({ name, slug }),
      ...validateSubject({ attributeName, category, linkSlug, resultSlug }),
      ...validateWeight(weight),
      ...(category === 'condition'
        ? validateConditionFields({ condition, falseScore, trueScore })
        : validateCategoryFields({
            ageMapRows,
            analysisFailScore,
            analysisPassScore,
            analysisWarnScore,
            attributeMapRows,
            category,
            missingScore,
            presentScore,
          })),
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  // fallow-ignore-next-line complexity
  const handleSave = () => {
    if (!validate()) return
    const base = {
      description: description.trim() || null,
      enabled,
      name: name.trim(),
      priority: parseInt(priority, 10) || 0,
      slug: slug.trim(),
      targets,
      weight: parseInt(weight, 10),
    }
    if (category === 'attribute') {
      const map = rowsToMap(attributeMapRows)
      onSave({
        ...base,
        attribute_name: attributeName.trim(),
        category: 'attribute',
        range_score_map: attributeMapType === 'range' ? map : null,
        value_score_map: attributeMapType === 'value' ? map : null,
      })
      return
    }
    if (category === 'presence') {
      onSave({
        ...base,
        attribute_name: attributeName.trim(),
        category: 'presence',
        missing_score: parseInt(missingScore, 10),
        present_score: parseInt(presentScore, 10),
      })
      return
    }
    if (category === 'link_presence') {
      onSave({
        ...base,
        category: 'link_presence',
        link_slug: linkSlug.trim(),
        missing_score: parseInt(missingScore, 10),
        present_score: parseInt(presentScore, 10),
      })
      return
    }
    if (category === 'analysis_result') {
      onSave({
        ...base,
        category: 'analysis_result',
        result_slug: resultSlug.trim(),
        status_score_map: {
          fail: parseInt(analysisFailScore, 10),
          pass: parseInt(analysisPassScore, 10),
          warn: parseInt(analysisWarnScore, 10),
        },
      })
      return
    }
    if (category === 'condition') {
      onSave({
        ...base,
        category: 'condition',
        condition,
        false_score: parseInt(falseScore, 10),
        true_score: parseInt(trueScore, 10),
      })
      return
    }
    // age
    const ageMap = rowsToMap(ageMapRows) ?? {}
    onSave({
      ...base,
      age_score_map: ageMap,
      attribute_name: attributeName.trim(),
      category: 'age',
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    handleSave()
  }

  const fieldError = (key: string) =>
    errors[key] ? (
      <div className="text-danger mt-1 flex items-center gap-1 text-xs">
        <AlertCircle className="size-3" />
        {errors[key]}
      </div>
    ) : null

  return (
    <div className="space-y-6">
      <FormHeader
        createLabel="Create Policy"
        isEditing={isEditing}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSave}
        subtitle={
          isEditing ? 'Update scoring policy' : 'Create a new scoring policy'
        }
        title={isEditing ? 'Edit Scoring Policy' : 'Create Scoring Policy'}
      />

      {!!error && (
        <ErrorBanner error={error} title="Failed to save scoring policy" />
      )}

      <form className="space-y-6" onSubmit={handleSubmit}>
        {/* Category — primary decision, shown first */}
        <Card>
          <CardHeader>
            <CardTitle>
              Policy Type <RequiredAsterisk />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex flex-wrap gap-2">
              {(
                [
                  'attribute',
                  'presence',
                  'link_presence',
                  'age',
                  'analysis_result',
                  'condition',
                ] as ScoringPolicyCategory[]
              ).map((c) => (
                <button
                  className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                    category === c
                      ? 'border-amber-text bg-amber-bg text-amber-text'
                      : 'border-input text-secondary hover:bg-secondary'
                  }`}
                  disabled={isEditing || isLoading}
                  key={c}
                  onClick={() => setCategory(c)}
                  type="button"
                >
                  {CATEGORY_LABELS[c]}
                </button>
              ))}
            </div>
            <p className="text-tertiary text-xs">
              {CATEGORY_DESCRIPTIONS[category]}
              {isEditing && ' Category cannot be changed after creation.'}
            </p>
          </CardContent>
        </Card>

        {/* Identity */}
        <Card>
          <CardHeader>
            <CardTitle>Identity</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <Label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="sp-name"
                >
                  Name <RequiredAsterisk />
                </Label>
                <Input
                  className={errors.name ? 'border-danger' : ''}
                  disabled={isLoading}
                  id="sp-name"
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Test Coverage"
                  value={name}
                />
                {fieldError('name')}
              </div>
              <div>
                <Label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="sp-slug"
                >
                  Slug <RequiredAsterisk />
                </Label>
                <Input
                  className={errors.slug ? 'border-danger' : ''}
                  disabled={isEditing || isLoading}
                  id="sp-slug"
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="e.g., test-coverage"
                  value={slug}
                />
                {fieldError('slug')}
              </div>
            </div>

            <div>
              <Label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="sp-description"
              >
                Description
              </Label>
              <Textarea
                className="resize-none rounded-lg"
                disabled={isLoading}
                id="sp-description"
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What does this policy measure?"
                rows={2}
                value={description}
              />
            </div>
          </CardContent>
        </Card>

        {/* Policy settings */}
        <Card>
          <CardHeader>
            <CardTitle>Policy Settings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {category === 'condition' ? null : category === 'link_presence' ? (
              <div>
                <Label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="sp-link-slug"
                >
                  Required Link Type <RequiredAsterisk />
                </Label>
                <Select
                  disabled={isLoading}
                  onValueChange={setLinkSlug}
                  value={linkSlug}
                >
                  <SelectTrigger
                    className={errors.link_slug ? 'border-danger' : ''}
                    id="sp-link-slug"
                  >
                    <SelectValue placeholder="Pick a link type" />
                  </SelectTrigger>
                  <SelectContent>
                    {sortedLinkDefinitions.length === 0 ? (
                      <div className="text-tertiary px-2 py-1.5 text-xs">
                        No link definitions configured for this organization
                      </div>
                    ) : (
                      sortedLinkDefinitions.map((def) => (
                        <SelectItem key={def.slug} value={def.slug}>
                          {def.name}
                        </SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
                <p className="text-tertiary mt-1 text-xs">
                  The link slug the project must have to score{' '}
                  <code>present_score</code>
                </p>
                {fieldError('link_slug')}
              </div>
            ) : category === 'analysis_result' ? (
              <div>
                <Label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="sp-result-slug"
                >
                  Analysis Result Slug <RequiredAsterisk />
                </Label>
                <Input
                  className={errors.result_slug ? 'border-danger' : ''}
                  disabled={isLoading}
                  id="sp-result-slug"
                  onChange={(e) => setResultSlug(e.target.value)}
                  placeholder="e.g., logzio:error-rate"
                  value={resultSlug}
                />
                <p className="text-tertiary mt-1 text-xs">
                  The stable slug emitted by an analysis plugin for the result
                  this policy scores
                </p>
                {fieldError('result_slug')}
              </div>
            ) : (
              <div>
                <Label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="sp-attribute"
                >
                  Attribute Name <RequiredAsterisk />
                </Label>
                <Input
                  className={errors.attribute_name ? 'border-danger' : ''}
                  disabled={isLoading}
                  id="sp-attribute"
                  onChange={(e) => setAttributeName(e.target.value)}
                  placeholder={
                    category === 'age'
                      ? 'e.g., oldest_open_pr'
                      : 'e.g., test_coverage'
                  }
                  value={attributeName}
                />
                <p className="text-tertiary mt-1 text-xs">
                  {category === 'age'
                    ? 'The datetime attribute on the project model whose age is scored'
                    : 'The blueprint attribute key this policy evaluates'}
                </p>
                {fieldError('attribute_name')}
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div>
                <Label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="sp-weight"
                >
                  Weight (0–100) <RequiredAsterisk />
                </Label>
                <Input
                  className={errors.weight ? 'border-danger' : ''}
                  disabled={isLoading}
                  id="sp-weight"
                  max={100}
                  min={0}
                  onChange={(e) => setWeight(e.target.value)}
                  type="number"
                  value={weight}
                />
                {fieldError('weight')}
              </div>

              <div>
                <Label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="sp-priority"
                >
                  Priority
                </Label>
                <Input
                  disabled={isLoading}
                  id="sp-priority"
                  onChange={(e) => setPriority(e.target.value)}
                  type="number"
                  value={priority}
                />
                <p className="text-tertiary mt-1 text-xs">
                  Lower numbers run first
                </p>
              </div>

              <div className="flex flex-col justify-center gap-1.5">
                <Label className="text-secondary text-sm">Enabled</Label>
                <Switch
                  checked={enabled}
                  disabled={isLoading}
                  onCheckedChange={setEnabled}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Score mapping — category-specific */}
        {category === 'attribute' && (
          <Card>
            <CardHeader>
              <CardTitle>Score Mapping</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label className="text-secondary mb-1.5 block text-sm">
                  Mapping type
                </Label>
                <div className="flex gap-3">
                  {(['value', 'range'] as const).map((t) => (
                    <button
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${
                        attributeMapType === t
                          ? 'border-amber-text bg-amber-bg text-amber-text'
                          : 'border-input text-secondary hover:bg-secondary'
                      }`}
                      disabled={isLoading}
                      key={t}
                      onClick={() => handleAttributeMapTypeChange(t)}
                      type="button"
                    >
                      {t === 'value' ? 'Value map' : 'Range map'}
                    </button>
                  ))}
                </div>
                <p className="text-tertiary mt-1.5 text-xs">
                  {attributeMapType === 'value'
                    ? 'Maps exact attribute values (strings) to scores'
                    : 'Maps numeric ranges like "0..70" to scores'}
                </p>
              </div>

              <MapEditor
                addLabel="Add entry"
                disabled={isLoading}
                error={errors.map}
                keyHeader={
                  attributeMapType === 'value'
                    ? 'Value (string)'
                    : 'Range (lo..hi)'
                }
                keyPlaceholder={
                  attributeMapType === 'value'
                    ? 'e.g., passing'
                    : 'e.g., 80..100'
                }
                onChange={setAttributeMapRows}
                rows={attributeMapRows}
                scoreHeader="Score (0–100)"
              />
            </CardContent>
          </Card>
        )}

        {category === 'age' && (
          <Card>
            <CardHeader>
              <CardTitle>Age Thresholds</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-tertiary text-xs">
                Each entry uses an operator (<code>&gt;</code>,{' '}
                <code>&gt;=</code>, <code>&lt;</code>, <code>&lt;=</code>,{' '}
                <code>==</code>) and a duration in <code>s</code> /{' '}
                <code>m</code> / <code>h</code> / <code>d</code> /{' '}
                <code>w</code> (for example, <code>&gt;30d</code>,{' '}
                <code>&lt;=7d</code>). Entries are evaluated in document order;
                the first match wins.
              </p>
              <MapEditor
                addLabel="Add threshold"
                disabled={isLoading}
                error={errors.age_map}
                keyHeader="Threshold"
                keyPlaceholder="e.g., >30d"
                onChange={setAgeMapRows}
                rows={ageMapRows}
                scoreHeader="Score (0–100)"
              />
            </CardContent>
          </Card>
        )}

        {category === 'analysis_result' && (
          <Card>
            <CardHeader>
              <CardTitle>Status Scores</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-tertiary text-xs">
                Map the analysis result's status to a 0–100 score.
              </p>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <div>
                  <Label
                    className="text-secondary mb-1.5 block text-sm"
                    htmlFor="sp-analysis-pass-score"
                  >
                    Pass score
                  </Label>
                  <Input
                    className={
                      errors.analysis_pass_score ? 'border-danger' : ''
                    }
                    disabled={isLoading}
                    id="sp-analysis-pass-score"
                    max={100}
                    min={0}
                    onChange={(e) => setAnalysisPassScore(e.target.value)}
                    type="number"
                    value={analysisPassScore}
                  />
                  {fieldError('analysis_pass_score')}
                </div>
                <div>
                  <Label
                    className="text-secondary mb-1.5 block text-sm"
                    htmlFor="sp-analysis-warn-score"
                  >
                    Warn score
                  </Label>
                  <Input
                    className={
                      errors.analysis_warn_score ? 'border-danger' : ''
                    }
                    disabled={isLoading}
                    id="sp-analysis-warn-score"
                    max={100}
                    min={0}
                    onChange={(e) => setAnalysisWarnScore(e.target.value)}
                    type="number"
                    value={analysisWarnScore}
                  />
                  {fieldError('analysis_warn_score')}
                </div>
                <div>
                  <Label
                    className="text-secondary mb-1.5 block text-sm"
                    htmlFor="sp-analysis-fail-score"
                  >
                    Fail score
                  </Label>
                  <Input
                    className={
                      errors.analysis_fail_score ? 'border-danger' : ''
                    }
                    disabled={isLoading}
                    id="sp-analysis-fail-score"
                    max={100}
                    min={0}
                    onChange={(e) => setAnalysisFailScore(e.target.value)}
                    type="number"
                    value={analysisFailScore}
                  />
                  {fieldError('analysis_fail_score')}
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {category === 'condition' && (
          <>
            <Card>
              <CardHeader>
                <CardTitle>
                  Condition <RequiredAsterisk />
                </CardTitle>
                <p className="text-tertiary text-xs">
                  Build a boolean expression over this project's attributes and
                  its outgoing dependencies. The whole tree evaluates to true or
                  false.
                </p>
              </CardHeader>
              <CardContent>
                <ConditionBuilder
                  disabled={isLoading}
                  falseScore={parseInt(falseScore, 10) || 0}
                  onChange={setCondition}
                  trueScore={parseInt(trueScore, 10) || 0}
                  value={condition}
                  weight={parseInt(weight, 10) || 0}
                />
                {fieldError('condition')}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Score Mapping</CardTitle>
                <p className="text-tertiary text-xs">
                  Map the boolean result to a 0–100 score, then it joins the
                  weighted average like any other policy.
                </p>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <Label
                      className="text-secondary mb-1.5 flex items-center gap-2 text-sm"
                      htmlFor="sp-true-score"
                    >
                      <span className="bg-success size-2 rounded-full" />
                      Score when true
                    </Label>
                    <Input
                      className={errors.true_score ? 'border-danger' : ''}
                      disabled={isLoading}
                      id="sp-true-score"
                      max={100}
                      min={0}
                      onChange={(e) => setTrueScore(e.target.value)}
                      type="number"
                      value={trueScore}
                    />
                    {fieldError('true_score')}
                  </div>
                  <div>
                    <Label
                      className="text-secondary mb-1.5 flex items-center gap-2 text-sm"
                      htmlFor="sp-false-score"
                    >
                      <span className="bg-danger size-2 rounded-full" />
                      Score when false
                    </Label>
                    <Input
                      className={errors.false_score ? 'border-danger' : ''}
                      disabled={isLoading}
                      id="sp-false-score"
                      max={100}
                      min={0}
                      onChange={(e) => setFalseScore(e.target.value)}
                      type="number"
                      value={falseScore}
                    />
                    {fieldError('false_score')}
                  </div>
                </div>
              </CardContent>
            </Card>
          </>
        )}

        {(category === 'presence' || category === 'link_presence') && (
          <Card>
            <CardHeader>
              <CardTitle>Scores</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <Label
                    className="text-secondary mb-1.5 block text-sm"
                    htmlFor="sp-present-score"
                  >
                    Present score (0–100)
                  </Label>
                  <Input
                    className={errors.present_score ? 'border-danger' : ''}
                    disabled={isLoading}
                    id="sp-present-score"
                    max={100}
                    min={0}
                    onChange={(e) => setPresentScore(e.target.value)}
                    type="number"
                    value={presentScore}
                  />
                  <p className="text-tertiary mt-1 text-xs">
                    {category === 'link_presence'
                      ? 'Score when the project has this link type'
                      : 'Score when the attribute has a non-empty value'}
                  </p>
                  {fieldError('present_score')}
                </div>
                <div>
                  <Label
                    className="text-secondary mb-1.5 block text-sm"
                    htmlFor="sp-missing-score"
                  >
                    Missing score (0–100)
                  </Label>
                  <Input
                    className={errors.missing_score ? 'border-danger' : ''}
                    disabled={isLoading}
                    id="sp-missing-score"
                    max={100}
                    min={0}
                    onChange={(e) => setMissingScore(e.target.value)}
                    type="number"
                    value={missingScore}
                  />
                  <p className="text-tertiary mt-1 text-xs">
                    {category === 'link_presence'
                      ? 'Score when the project does not have this link type'
                      : 'Score when the attribute is null, empty, or whitespace'}
                  </p>
                  {fieldError('missing_score')}
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Target project types */}
        <Card>
          <CardHeader>
            <CardTitle>Target Project Types</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-tertiary mb-3 text-sm">
              Leave all unchecked to apply this policy to every project type.
            </p>
            {ptLoading ? (
              <p className="text-tertiary text-xs italic">
                Loading project types...
              </p>
            ) : ptIsError ? (
              <p className="text-danger text-xs italic">
                Failed to load project types
              </p>
            ) : projectTypes.length === 0 ? (
              <p className="text-tertiary text-xs italic">
                No project types available
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                {projectTypes.map((pt) => (
                  <div className="flex items-center gap-2" key={pt.slug}>
                    <Checkbox
                      checked={targets.includes(pt.slug)}
                      disabled={isLoading}
                      id={`target-pt-${pt.slug}`}
                      onCheckedChange={() =>
                        setTargets((prev) =>
                          prev.includes(pt.slug)
                            ? prev.filter((s) => s !== pt.slug)
                            : [...prev, pt.slug],
                        )
                      }
                    />
                    <Label
                      className="text-secondary cursor-pointer text-sm select-none"
                      htmlFor={`target-pt-${pt.slug}`}
                    >
                      {pt.name}
                    </Label>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </form>
    </div>
  )
}

function MapEditor({
  addLabel,
  disabled = false,
  error,
  keyHeader,
  keyPlaceholder,
  onChange,
  rows,
  scoreHeader,
}: MapEditorProps) {
  const updateRow = (i: number, field: 'key' | 'score', value: string) => {
    const next = [...rows]
    next[i] = { ...next[i], [field]: value }
    onChange(next)
  }

  const addRow = () => onChange([...rows, emptyRow()])
  const removeRow = (i: number) => onChange(rows.filter((_, idx) => idx !== i))

  return (
    <div className="space-y-2">
      <div className="text-tertiary grid grid-cols-[1fr_100px_32px] gap-2 text-xs">
        <span>{keyHeader}</span>
        <span>{scoreHeader}</span>
        <span />
      </div>
      {rows.map((row, i) => (
        <div
          className="grid grid-cols-[1fr_100px_32px] items-center gap-2"
          key={row.id}
        >
          <Input
            disabled={disabled}
            onChange={(e) => updateRow(i, 'key', e.target.value)}
            placeholder={keyPlaceholder}
            value={row.key}
          />
          <Input
            disabled={disabled}
            max={100}
            min={0}
            onChange={(e) => updateRow(i, 'score', e.target.value)}
            placeholder="100"
            type="number"
            value={row.score}
          />
          <Button
            disabled={disabled || rows.length === 1}
            onClick={() => removeRow(i)}
            size="sm"
            type="button"
            variant="ghost"
          >
            <Trash2 className="text-secondary size-4" />
          </Button>
        </div>
      ))}
      <Button
        className="mt-1"
        disabled={disabled}
        onClick={addRow}
        size="sm"
        type="button"
        variant="outline"
      >
        <Plus className="mr-1.5 size-3.5" />
        {addLabel}
      </Button>
      {error && (
        <div className="text-danger mt-1 flex items-center gap-1 text-xs">
          <AlertCircle className="size-3" />
          {error}
        </div>
      )}
    </div>
  )
}

function newRow(key: string, score: string): MapRow {
  rowIdCounter += 1
  return { id: `row-${rowIdCounter}`, key, score }
}

function parseMapToRows(
  map: null | Record<string, number> | undefined,
): MapRow[] {
  if (!map) return [emptyRow()]
  const rows = Object.entries(map).map(([key, score]) =>
    newRow(key, String(score)),
  )
  return rows.length > 0 ? rows : [emptyRow()]
}

// fallow-ignore-next-line complexity
function rowsToMap(rows: MapRow[]): null | Record<string, number> {
  const out: Record<string, number> = {}
  for (const row of rows) {
    const trimmed = row.key.trim()
    const val = parseInt(row.score, 10)
    if (trimmed && !isNaN(val)) {
      out[trimmed] = val
    }
  }
  return Object.keys(out).length > 0 ? out : null
}

const AGE_THRESHOLD_RE = /^(>=|>|<=|<|==)\s*\d+(?:\.\d+)?\s*[smhdw]$/

let rowIdCounter = 0
// fallow-ignore-next-line complexity
function conditionHasEmptyAttribute(node: Condition): boolean {
  const n = node as {
    all?: Condition[]
    any?: Condition[]
    attribute?: string
    not?: Condition
    op?: string
    relationship?: { where: Condition }
  }
  if (n.all != null) return n.all.some(conditionHasEmptyAttribute)
  if (n.any != null) return n.any.some(conditionHasEmptyAttribute)
  if (n.not != null) return conditionHasEmptyAttribute(n.not)
  if (n.relationship != null) {
    return conditionHasEmptyAttribute(n.relationship.where)
  }
  return !n.attribute || !n.attribute.trim()
}

function emptyRow(): MapRow {
  return newRow('', '')
}

function isAgeThreshold(value: string): boolean {
  return AGE_THRESHOLD_RE.test(value.trim())
}

function isScoreInRange(value: string): boolean {
  const n = parseInt(value, 10)
  return !isNaN(n) && n >= 0 && n <= 100
}

function validateAgeMap(rows: MapRow[]): null | string {
  const valid = rows.filter((r) => r.key.trim() && r.score.trim())
  if (valid.length === 0) return 'At least one age threshold is required'
  const anyInvalid = valid.some(
    (r) => !isAgeThreshold(r.key.trim()) || !isScoreInRange(r.score),
  )
  return anyInvalid
    ? 'Each entry must use a threshold like ">30d" or "<=7d" and a score 0–100'
    : null
}

function validateAttributeMap(rows: MapRow[]): null | string {
  const valid = rows.filter((r) => r.key.trim() && r.score.trim())
  if (valid.length === 0) return 'At least one mapping entry is required'
  if (valid.some((r) => !isScoreInRange(r.score))) {
    return 'All scores must be between 0 and 100'
  }
  return null
}

// fallow-ignore-next-line complexity
function validateCategoryFields(args: {
  ageMapRows: MapRow[]
  analysisFailScore: string
  analysisPassScore: string
  analysisWarnScore: string
  attributeMapRows: MapRow[]
  category: ScoringPolicyCategory
  missingScore: string
  presentScore: string
}): Record<string, string> {
  if (args.category === 'age') {
    const err = validateAgeMap(args.ageMapRows)
    return err ? { age_map: err } : {}
  }
  if (args.category === 'attribute') {
    const err = validateAttributeMap(args.attributeMapRows)
    return err ? { map: err } : {}
  }
  if (args.category === 'analysis_result') {
    const errors: Record<string, string> = {}
    if (!isScoreInRange(args.analysisPassScore))
      errors.analysis_pass_score = 'Score must be 0–100'
    if (!isScoreInRange(args.analysisWarnScore))
      errors.analysis_warn_score = 'Score must be 0–100'
    if (!isScoreInRange(args.analysisFailScore))
      errors.analysis_fail_score = 'Score must be 0–100'
    return errors
  }
  return validatePresenceScores(args.presentScore, args.missingScore)
}

function validateConditionFields(args: {
  condition: Condition
  falseScore: string
  trueScore: string
}): Record<string, string> {
  const errors: Record<string, string> = {}
  if (conditionHasEmptyAttribute(args.condition)) {
    errors.condition = 'Every attribute rule needs an attribute name'
  }
  if (!isScoreInRange(args.trueScore)) errors.true_score = 'Score must be 0–100'
  if (!isScoreInRange(args.falseScore))
    errors.false_score = 'Score must be 0–100'
  return errors
}

function validateIdentity(args: {
  name: string
  slug: string
}): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!args.name.trim()) errors.name = 'Name is required'
  if (!args.slug.trim()) errors.slug = 'Slug is required'
  else if (!/^[a-z0-9_-]+$/.test(args.slug)) {
    errors.slug =
      'Slug must be lowercase letters, numbers, hyphens, or underscores'
  }
  return errors
}

function validatePresenceScores(
  presentScore: string,
  missingScore: string,
): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!isScoreInRange(presentScore))
    errors.present_score = 'Score must be 0–100'
  if (!isScoreInRange(missingScore))
    errors.missing_score = 'Score must be 0–100'
  return errors
}

// fallow-ignore-next-line complexity
function validateSubject(args: {
  attributeName: string
  category: ScoringPolicyCategory
  linkSlug: string
  resultSlug: string
}): Record<string, string> {
  if (args.category === 'link_presence') {
    return args.linkSlug.trim() ? {} : { link_slug: 'Link type is required' }
  }
  if (args.category === 'analysis_result') {
    return args.resultSlug.trim()
      ? {}
      : { result_slug: 'Result slug is required' }
  }
  if (args.category === 'condition') return {}
  return args.attributeName.trim()
    ? {}
    : { attribute_name: 'Attribute name is required' }
}

function validateWeight(weight: string): Record<string, string> {
  const w = parseInt(weight, 10)
  return isNaN(w) || w < 0 || w > 100 ? { weight: 'Weight must be 0–100' } : {}
}

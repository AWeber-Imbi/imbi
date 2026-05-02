import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Plus, Trash2 } from 'lucide-react'

import { listProjectTypes } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { useOrganization } from '@/contexts/OrganizationContext'
import { slugify } from '@/lib/utils'
import type { ScoringPolicy, ScoringPolicyCreate } from '@/types'

interface MapRow {
  key: string
  score: string
}

type MapType = 'range' | 'value'

interface ScoringPolicyFormProps {
  error?: unknown
  isLoading?: boolean
  onCancel: () => void
  onSave: (data: ScoringPolicyCreate) => void
  policy: null | ScoringPolicy
}

export function ScoringPolicyForm({
  error,
  isLoading = false,
  onCancel,
  onSave,
  policy,
}: ScoringPolicyFormProps) {
  const isEditing = policy !== null

  const [name, setName] = useState(policy?.name ?? '')
  const [slug, setSlug] = useState(policy?.slug ?? '')
  const [description, setDescription] = useState(policy?.description ?? '')
  const [attributeName, setAttributeName] = useState(
    policy?.attribute_name ?? '',
  )
  const [weight, setWeight] = useState(String(policy?.weight ?? 50))
  const [priority, setPriority] = useState(String(policy?.priority ?? 0))
  const [enabled, setEnabled] = useState(policy?.enabled ?? true)
  const [targets, setTargets] = useState<string[]>(policy?.targets ?? [])
  const [mapType, setMapType] = useState<MapType>(
    policy?.range_score_map != null ? 'range' : 'value',
  )
  const [mapRows, setMapRows] = useState<MapRow[]>(
    mapType === 'range'
      ? parseMapToRows(policy?.range_score_map)
      : parseMapToRows(policy?.value_score_map),
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
    queryKey: ['projectTypes', orgSlug],
    staleTime: 5 * 60 * 1000,
  })

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) setSlug(slugify(value))
  }

  const handleMapTypeChange = (type: MapType) => {
    setMapType(type)
    setMapRows([{ key: '', score: '' }])
  }

  const addMapRow = () =>
    setMapRows((prev) => [...prev, { key: '', score: '' }])

  const removeMapRow = (i: number) =>
    setMapRows((prev) => prev.filter((_, idx) => idx !== i))

  const updateMapRow = (i: number, field: 'key' | 'score', value: string) => {
    setMapRows((prev) => {
      const next = [...prev]
      next[i] = { ...next[i], [field]: value }
      return next
    })
  }

  const toggleTarget = (slug: string) => {
    setTargets((prev) =>
      prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug],
    )
  }

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9_-]+$/.test(slug))
      newErrors.slug =
        'Slug must be lowercase letters, numbers, hyphens, or underscores'
    if (!attributeName.trim())
      newErrors.attribute_name = 'Attribute name is required'
    const w = parseInt(weight, 10)
    if (isNaN(w) || w < 0 || w > 100) newErrors.weight = 'Weight must be 0–100'
    const hasMap = mapRows.some((r) => r.key.trim() && r.score.trim())
    if (!hasMap) newErrors.map = 'At least one mapping entry is required'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSave = () => {
    if (!validate()) return
    const map = rowsToMap(mapRows)
    onSave({
      attribute_name: attributeName.trim(),
      description: description.trim() || null,
      enabled,
      name: name.trim(),
      priority: parseInt(priority, 10) || 0,
      range_score_map: mapType === 'range' ? map : null,
      slug: slug.trim(),
      targets,
      value_score_map: mapType === 'value' ? map : null,
      weight: parseInt(weight, 10),
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    handleSave()
  }

  const fieldError = (key: string) =>
    errors[key] ? (
      <div className="mt-1 flex items-center gap-1 text-xs text-danger">
        <AlertCircle className="h-3 w-3" />
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
        {/* Identity */}
        <Card>
          <CardHeader>
            <CardTitle>Identity</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label
                  className="mb-1.5 block text-sm text-secondary"
                  htmlFor="sp-name"
                >
                  Name <span className="text-danger">*</span>
                </label>
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
                <label
                  className="mb-1.5 block text-sm text-secondary"
                  htmlFor="sp-slug"
                >
                  Slug <span className="text-danger">*</span>
                </label>
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
              <label
                className="mb-1.5 block text-sm text-secondary"
                htmlFor="sp-description"
              >
                Description
              </label>
              <textarea
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
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
            <div>
              <label
                className="mb-1.5 block text-sm text-secondary"
                htmlFor="sp-attribute"
              >
                Attribute Name <span className="text-danger">*</span>
              </label>
              <Input
                className={errors.attribute_name ? 'border-danger' : ''}
                disabled={isLoading}
                id="sp-attribute"
                onChange={(e) => setAttributeName(e.target.value)}
                placeholder="e.g., test_coverage"
                value={attributeName}
              />
              <p className="mt-1 text-xs text-tertiary">
                The blueprint attribute key this policy evaluates
              </p>
              {fieldError('attribute_name')}
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div>
                <label
                  className="mb-1.5 block text-sm text-secondary"
                  htmlFor="sp-weight"
                >
                  Weight (0–100) <span className="text-danger">*</span>
                </label>
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
                <label
                  className="mb-1.5 block text-sm text-secondary"
                  htmlFor="sp-priority"
                >
                  Priority
                </label>
                <Input
                  disabled={isLoading}
                  id="sp-priority"
                  onChange={(e) => setPriority(e.target.value)}
                  type="number"
                  value={priority}
                />
                <p className="mt-1 text-xs text-tertiary">
                  Lower numbers run first
                </p>
              </div>

              <div className="flex flex-col justify-center gap-1.5">
                <label className="text-sm text-secondary">Enabled</label>
                <Switch
                  checked={enabled}
                  disabled={isLoading}
                  onCheckedChange={setEnabled}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Score mapping */}
        <Card>
          <CardHeader>
            <CardTitle>Score Mapping</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Mapping type
              </label>
              <div className="flex gap-3">
                {(['value', 'range'] as const).map((t) => (
                  <button
                    className={`rounded-lg border px-4 py-2 text-sm transition-colors ${
                      mapType === t
                        ? 'border-amber-text bg-amber-bg text-amber-text'
                        : 'border-input text-secondary hover:bg-secondary'
                    }`}
                    disabled={isLoading}
                    key={t}
                    onClick={() => handleMapTypeChange(t)}
                    type="button"
                  >
                    {t === 'value' ? 'Value map' : 'Range map'}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-xs text-tertiary">
                {mapType === 'value'
                  ? 'Maps exact attribute values (strings) to scores'
                  : 'Maps numeric ranges like "0..70" to scores'}
              </p>
            </div>

            <div className="space-y-2">
              <div className="grid grid-cols-[1fr_100px_32px] gap-2 text-xs text-tertiary">
                <span>
                  {mapType === 'value' ? 'Value (string)' : 'Range (lo..hi)'}
                </span>
                <span>Score (0–100)</span>
                <span />
              </div>

              {mapRows.map((row, i) => (
                <div
                  className="grid grid-cols-[1fr_100px_32px] items-center gap-2"
                  key={i}
                >
                  <Input
                    disabled={isLoading}
                    onChange={(e) => updateMapRow(i, 'key', e.target.value)}
                    placeholder={
                      mapType === 'value' ? 'e.g., passing' : 'e.g., 80..100'
                    }
                    value={row.key}
                  />
                  <Input
                    disabled={isLoading}
                    max={100}
                    min={0}
                    onChange={(e) => updateMapRow(i, 'score', e.target.value)}
                    placeholder="100"
                    type="number"
                    value={row.score}
                  />
                  <Button
                    disabled={isLoading || mapRows.length === 1}
                    onClick={() => removeMapRow(i)}
                    size="sm"
                    type="button"
                    variant="ghost"
                  >
                    <Trash2 className="h-4 w-4 text-secondary" />
                  </Button>
                </div>
              ))}

              <Button
                className="mt-1"
                disabled={isLoading}
                onClick={addMapRow}
                size="sm"
                type="button"
                variant="outline"
              >
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                Add entry
              </Button>

              {fieldError('map')}
            </div>
          </CardContent>
        </Card>

        {/* Target project types */}
        <Card>
          <CardHeader>
            <CardTitle>Target Project Types</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-tertiary">
              Leave all unchecked to apply this policy to every project type.
            </p>
            {ptLoading ? (
              <p className="text-xs italic text-tertiary">
                Loading project types...
              </p>
            ) : ptIsError ? (
              <p className="text-xs italic text-danger">
                Failed to load project types
              </p>
            ) : projectTypes.length === 0 ? (
              <p className="text-xs italic text-tertiary">
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
                      onCheckedChange={() => toggleTarget(pt.slug)}
                    />
                    <label
                      className="cursor-pointer select-none text-sm text-secondary"
                      htmlFor={`target-pt-${pt.slug}`}
                    >
                      {pt.name}
                    </label>
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

function parseMapToRows(
  map: null | Record<string, number> | undefined,
): MapRow[] {
  if (!map) return [{ key: '', score: '' }]
  const rows = Object.entries(map).map(([key, score]) => ({
    key,
    score: String(score),
  }))
  return rows.length > 0 ? rows : [{ key: '', score: '' }]
}

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

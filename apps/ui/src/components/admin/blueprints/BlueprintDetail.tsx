import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Edit2,
  FileJson,
  Filter,
  AlertCircle,
  CheckCircle,
  XCircle,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Hash,
  ToggleLeft,
  Type,
  List,
  Braces,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { CardTitle } from '@/components/ui/card'
import { LoadingState } from '@/components/ui/loading-state'
import { getBlueprint } from '@/api/endpoints'
import { getTypeSwatch } from '../BlueprintManagement'
import { LabelChip } from '@/components/ui/label-chip'
import { parseFilterFromBlueprint } from '@/lib/utils'
import type { SchemaProperty } from '@/types'

interface BlueprintDetailProps {
  blueprintKey: { type: string; slug: string }
  blueprintTypes: string[]
  onEdit: () => void
  onBack: () => void
}

const TYPE_ICONS: Record<string, typeof Type> = {
  string: Type,
  integer: Hash,
  number: Hash,
  boolean: ToggleLeft,
  array: List,
  object: Braces,
}

function parseSchemaProperties(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  schema: any,
): { properties: SchemaProperty[]; raw: string } {
  let parsed = schema
  if (typeof schema === 'string') {
    try {
      parsed = JSON.parse(schema)
    } catch {
      return {
        properties: [],
        raw: typeof schema === 'string' ? schema : '{}',
      }
    }
  }

  const raw = JSON.stringify(parsed, null, 2)
  const props = parsed?.properties || {}
  const required = (parsed?.required || []) as string[]
  const properties: SchemaProperty[] = []

  for (const [name, propSchema] of Object.entries(props)) {
    const ps = propSchema as Record<string, unknown>
    const xUi = ps['x-ui'] as Record<string, unknown> | undefined
    properties.push({
      id: name,
      name,
      type: (ps.type as SchemaProperty['type']) || 'string',
      format: ps.format as string | undefined,
      description: ps.description as string | undefined,
      required: required.includes(name),
      defaultValue: ps.default !== undefined ? String(ps.default) : undefined,
      enumValues: ps.enum as string[] | undefined,
      minimum: ps.minimum as number | undefined,
      maximum: ps.maximum as number | undefined,
      minLength: ps.minLength as number | undefined,
      maxLength: ps.maxLength as number | undefined,
      colorMap: xUi?.['color-map'] as Record<string, string> | undefined,
      iconMap: xUi?.['icon-map'] as Record<string, string> | undefined,
      colorRange: xUi?.['color-range'] as Record<string, string> | undefined,
      iconRange: xUi?.['icon-range'] as Record<string, string> | undefined,
      colorAge: xUi?.['color-age'] as Record<string, string> | undefined,
      iconAge: xUi?.['icon-age'] as Record<string, string> | undefined,
    })
  }

  return { properties, raw }
}

function hasConstraints(prop: SchemaProperty): boolean {
  return (
    prop.defaultValue !== undefined ||
    prop.minimum !== undefined ||
    prop.maximum !== undefined ||
    prop.minLength !== undefined ||
    prop.maxLength !== undefined
  )
}

export function BlueprintDetail({
  blueprintKey,
  blueprintTypes,
  onEdit,
  onBack,
}: BlueprintDetailProps) {
  const [rawSchemaOpen, setRawSchemaOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const {
    data: blueprint,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['blueprint', blueprintKey.type, blueprintKey.slug],
    queryFn: ({ signal }) =>
      getBlueprint(blueprintKey.type, blueprintKey.slug, signal),
  })

  if (isLoading) {
    return <LoadingState label="Loading blueprint..." />
  }

  if (error || !blueprint) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger">
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load blueprint</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'Blueprint not found'}
          </div>
        </div>
      </div>
    )
  }

  const { properties, raw } = parseSchemaProperties(blueprint.json_schema)

  // Parse filter
  const parsedFilter = parseFilterFromBlueprint(blueprint.filter)
  const hasFilter = parsedFilter !== null

  const handleCopy = () => {
    // Parse json_schema from string back to object
    let schemaObj: Record<string, unknown> = {}
    try {
      schemaObj =
        typeof blueprint.json_schema === 'string'
          ? JSON.parse(blueprint.json_schema)
          : blueprint.json_schema
    } catch {
      // fallback
    }

    const exportObj: Record<string, unknown> = {
      name: blueprint.name,
      slug: blueprint.slug,
      kind: blueprint.kind || 'node',
      ...(blueprint.kind === 'relationship'
        ? {
            source: blueprint.source ?? '',
            target: blueprint.target ?? '',
            edge: blueprint.edge ?? '',
          }
        : { type: blueprint.type }),
      ...(blueprint.description ? { description: blueprint.description } : {}),
      enabled: blueprint.enabled,
      priority: blueprint.priority,
      ...(parsedFilter &&
      (parsedFilter.project_type?.length > 0 ||
        parsedFilter.environment?.length > 0)
        ? { filter: parsedFilter }
        : {}),
      json_schema: schemaObj,
    }

    navigator.clipboard
      .writeText(JSON.stringify(exportObj, null, 2))
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      })
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button variant="outline" onClick={onBack}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Blueprint info card */}
      <div className="rounded-lg border border-border bg-card">
        {/* Title row */}
        <div className="flex items-start justify-between border-b border-tertiary px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-info p-2">
              <FileJson className="h-6 w-6 text-info" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <CardTitle>{blueprint.name}</CardTitle>
                <LabelChip
                  hex={getTypeSwatch(
                    blueprint.kind === 'relationship'
                      ? 'relationship'
                      : blueprint.type || '',
                    blueprintTypes,
                  )}
                >
                  {blueprint.kind === 'relationship'
                    ? `${blueprint.source ?? '?'} → ${blueprint.target ?? '?'} (${blueprint.edge ?? '?'})`
                    : blueprint.type}
                </LabelChip>
              </div>
              <p className="mt-1 text-secondary">
                {blueprint.description || 'No description'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={handleCopy}>
              {copied ? (
                <Check className="mr-2 h-4 w-4 text-green-500" />
              ) : (
                <Copy className="mr-2 h-4 w-4" />
              )}
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button
              onClick={onEdit}
              className="bg-action text-action-foreground hover:bg-action-hover"
            >
              <Edit2 className="mr-2 h-4 w-4" />
              Edit Blueprint
            </Button>
          </div>
        </div>

        {/* Metadata row */}
        <div className="flex flex-wrap items-center gap-6 px-6 py-4">
          <div>
            <div className="text-xs text-secondary">Slug</div>
            <div className="font-mono text-sm text-primary">
              {blueprint.slug}
            </div>
          </div>
          <div className="h-8 border-l border-tertiary" />
          <div>
            <div className="text-xs text-secondary">Enabled</div>
            <div className="flex items-center gap-1.5">
              {blueprint.enabled ? (
                <>
                  <CheckCircle className="h-4 w-4 text-green-500" />
                  <span className="text-sm text-primary">Yes</span>
                </>
              ) : (
                <>
                  <XCircle className="h-4 w-4 text-gray-400" />
                  <span className="text-sm text-primary">No</span>
                </>
              )}
            </div>
          </div>
          <div className="h-8 border-l border-tertiary" />
          <div>
            <div className="text-xs text-secondary">Priority</div>
            <div className="text-sm text-primary">{blueprint.priority}</div>
          </div>
          <div className="h-8 border-l border-tertiary" />
          <div>
            <div className="text-xs text-secondary">Version</div>
            <div className="text-sm text-primary">v{blueprint.version}</div>
          </div>
          <div className="h-8 border-l border-tertiary" />
          <div>
            <div className="text-xs text-secondary">Properties</div>
            <div className="text-sm text-primary">{properties.length}</div>
          </div>
          <div className="h-8 border-l border-tertiary" />
          <div>
            <div className="text-xs text-secondary">Filter</div>
            <div className="flex items-center gap-1.5">
              {hasFilter ? (
                <>
                  <Filter className="h-4 w-4 text-warning" />
                  <span className="text-sm text-primary">Active</span>
                </>
              ) : (
                <span className="text-sm text-tertiary">None</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Conditional Filter detail */}
      {hasFilter && parsedFilter && (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-tertiary px-6 py-4">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-warning" />
              <h3 className="text-sm font-medium text-primary">
                Conditional Filter
              </h3>
              <span className="ml-1 text-xs text-tertiary">
                Only applies to matching entities
              </span>
            </div>
          </div>
          <div className="space-y-4 px-6 py-4">
            {(parsedFilter.project_type?.length ?? 0) > 0 && (
              <div>
                <div
                  className={
                    'mb-2 text-xs font-medium uppercase tracking-wider text-tertiary'
                  }
                >
                  Project Types
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {parsedFilter.project_type.map((pt) => (
                    <Badge
                      key={pt}
                      variant="info"
                      className="rounded-md border-info px-2.5 py-1 text-sm"
                    >
                      {pt}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {(parsedFilter.environment?.length ?? 0) > 0 && (
              <div>
                <div
                  className={
                    'mb-2 text-xs font-medium uppercase tracking-wider text-tertiary'
                  }
                >
                  Environments
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {parsedFilter.environment.map((env) => (
                    <Badge
                      key={env}
                      variant="success"
                      className="rounded-md border-success px-2.5 py-1 text-sm"
                    >
                      {env}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Schema Properties */}
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-tertiary px-6 py-4">
          <h3 className="text-sm font-medium text-primary">
            Schema Properties
          </h3>
        </div>

        {properties.length === 0 ? (
          <div className="py-8 text-center text-tertiary">
            <FileJson className="mx-auto mb-2 h-8 w-8 opacity-50" />
            <div>No properties defined</div>
          </div>
        ) : (
          <div className="divide-y divide-tertiary">
            {properties.map((prop) => {
              const IconComponent = TYPE_ICONS[prop.type] || Type
              return (
                <div key={prop.name} className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <IconComponent className="h-4 w-4 flex-shrink-0 text-tertiary" />
                    <code className="rounded bg-secondary px-2 py-1 text-sm font-medium text-info">
                      {prop.name}
                    </code>
                    <Badge variant="secondary">
                      {prop.type}
                      {prop.format ? ` / ${prop.format}` : ''}
                    </Badge>
                    {prop.required && <Badge variant="danger">Required</Badge>}
                  </div>

                  {prop.description && (
                    <p className="ml-7 mt-1.5 text-sm text-secondary">
                      {prop.description}
                    </p>
                  )}

                  {/* Enum values as badges */}
                  {prop.enumValues && prop.enumValues.length > 0 && (
                    <div className="ml-7 mt-2 flex flex-wrap gap-1.5">
                      {prop.enumValues.map((val) => (
                        <Badge
                          key={val}
                          variant="secondary"
                          className="border border-input font-mono text-secondary"
                        >
                          {val}
                        </Badge>
                      ))}
                    </div>
                  )}

                  {/* x-ui maps */}
                  {(() => {
                    const uiMaps: [
                      string,
                      Record<string, string> | undefined,
                    ][] = [
                      ['color-map', prop.colorMap],
                      ['icon-map', prop.iconMap],
                      ['color-range', prop.colorRange],
                      ['icon-range', prop.iconRange],
                      ['color-age', prop.colorAge],
                      ['icon-age', prop.iconAge],
                    ]
                    const activeMaps = uiMaps.filter(
                      ([, m]) => m && Object.keys(m).length > 0,
                    )
                    if (activeMaps.length === 0) return null
                    const isColorType = (name: string) =>
                      name.startsWith('color-')
                    return (
                      <div className="ml-7 mt-2 flex flex-wrap gap-4">
                        {activeMaps.map(([name, map]) => (
                          <div key={name}>
                            <span className="text-xs text-tertiary">
                              {name}
                            </span>
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              {Object.entries(map!).map(([key, val]) => (
                                <Badge
                                  key={key}
                                  variant="secondary"
                                  className="gap-1.5 border border-input font-mono text-secondary"
                                >
                                  {isColorType(name) ? (
                                    <>
                                      <span
                                        className="inline-block h-2 w-2 flex-shrink-0 rounded-full"
                                        style={{ backgroundColor: val }}
                                      />
                                      {key}
                                    </>
                                  ) : (
                                    <>
                                      {key} → {val}
                                    </>
                                  )}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  })()}

                  {/* Constraints row */}
                  {hasConstraints(prop) && (
                    <div className="ml-7 mt-2 flex flex-wrap gap-4">
                      {prop.defaultValue !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-tertiary">Default</span>
                          <code className="rounded bg-secondary px-1.5 py-0.5 text-xs text-primary">
                            {prop.defaultValue}
                          </code>
                        </div>
                      )}
                      {prop.minimum !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-tertiary">Min</span>
                          <code className="rounded bg-secondary px-1.5 py-0.5 text-xs text-primary">
                            {prop.minimum}
                          </code>
                        </div>
                      )}
                      {prop.maximum !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-tertiary">Max</span>
                          <code className="rounded bg-secondary px-1.5 py-0.5 text-xs text-primary">
                            {prop.maximum}
                          </code>
                        </div>
                      )}
                      {prop.minLength !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-tertiary">
                            Min length
                          </span>
                          <code className="rounded bg-secondary px-1.5 py-0.5 text-xs text-primary">
                            {prop.minLength}
                          </code>
                        </div>
                      )}
                      {prop.maxLength !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-tertiary">
                            Max length
                          </span>
                          <code className="rounded bg-secondary px-1.5 py-0.5 text-xs text-primary">
                            {prop.maxLength}
                          </code>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Raw JSON Schema (collapsible) */}
      <div className="rounded-lg border border-border bg-card">
        <button
          onClick={() => setRawSchemaOpen(!rawSchemaOpen)}
          className={`flex w-full items-center gap-2 px-6 py-4 text-left hover:bg-secondary ${rawSchemaOpen ? 'border-b border-tertiary' : ''}`}
        >
          {rawSchemaOpen ? (
            <ChevronDown className="h-4 w-4 text-tertiary" />
          ) : (
            <ChevronRight className="h-4 w-4 text-tertiary" />
          )}
          <h3 className="text-sm font-medium text-primary">Raw JSON Schema</h3>
          <span className="text-xs text-tertiary">
            {raw.split('\n').length} lines
          </span>
        </button>
        {rawSchemaOpen && (
          <pre className="overflow-x-auto px-6 py-4 font-mono text-sm leading-relaxed text-primary">
            {raw}
          </pre>
        )}
      </div>
    </div>
  )
}

import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Braces,
  Check,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Copy,
  Edit2,
  FileJson,
  Filter,
  Hash,
  List,
  ToggleLeft,
  Type,
  XCircle,
} from 'lucide-react'

import { getBlueprint } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CardTitle } from '@/components/ui/card'
import { LabelChip } from '@/components/ui/label-chip'
import { LoadingState } from '@/components/ui/loading-state'
import { parseFilterFromBlueprint } from '@/lib/utils'
import type { SchemaProperty } from '@/types'

import { getTypeSwatch } from './typeSwatch'

interface BlueprintDetailProps {
  blueprintKey: { slug: string; type: string }
  blueprintTypes: string[]
  onBack: () => void
  onEdit: () => void
}

const TYPE_ICONS: Record<string, typeof Type> = {
  array: List,
  boolean: ToggleLeft,
  integer: Hash,
  number: Hash,
  object: Braces,
  string: Type,
}

export function BlueprintDetail({
  blueprintKey,
  blueprintTypes,
  onBack,
  onEdit,
}: BlueprintDetailProps) {
  const [rawSchemaOpen, setRawSchemaOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const {
    data: blueprint,
    error,
    isLoading,
  } = useQuery({
    queryFn: ({ signal }) =>
      getBlueprint(blueprintKey.type, blueprintKey.slug, signal),
    queryKey: ['blueprint', blueprintKey.type, blueprintKey.slug],
  })

  if (isLoading) {
    return <LoadingState label="Loading blueprint..." />
  }

  if (error || !blueprint) {
    return (
      <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4">
        <AlertCircle className="size-5 shrink-0" />
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
      kind: blueprint.kind || 'node',
      name: blueprint.name,
      slug: blueprint.slug,
      ...(blueprint.kind === 'relationship'
        ? {
            edge: blueprint.edge ?? '',
            source: blueprint.source ?? '',
            target: blueprint.target ?? '',
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
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 size-4" />
          Back
        </Button>
      </div>

      {/* Blueprint info card */}
      <div className="border-border bg-card rounded-lg border">
        {/* Title row */}
        <div className="border-tertiary flex items-start justify-between border-b px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="bg-info rounded-lg p-2">
              <FileJson className="text-info size-6" />
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
              <p className="text-secondary mt-1">
                {blueprint.description || 'No description'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleCopy} variant="outline">
              {copied ? (
                <Check className="mr-2 size-4 text-green-500" />
              ) : (
                <Copy className="mr-2 size-4" />
              )}
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button
              className="bg-action text-action-foreground hover:bg-action-hover"
              onClick={onEdit}
            >
              <Edit2 className="mr-2 size-4" />
              Edit Blueprint
            </Button>
          </div>
        </div>

        {/* Metadata row */}
        <div className="flex flex-wrap items-center gap-6 px-6 py-4">
          <div>
            <div className="text-secondary text-xs">Slug</div>
            <div className="text-primary font-mono text-sm">
              {blueprint.slug}
            </div>
          </div>
          <div className="border-tertiary h-8 border-l" />
          <div>
            <div className="text-secondary text-xs">Enabled</div>
            <div className="flex items-center gap-1.5">
              {blueprint.enabled ? (
                <>
                  <CheckCircle className="size-4 text-green-500" />
                  <span className="text-primary text-sm">Yes</span>
                </>
              ) : (
                <>
                  <XCircle className="size-4 text-gray-400" />
                  <span className="text-primary text-sm">No</span>
                </>
              )}
            </div>
          </div>
          <div className="border-tertiary h-8 border-l" />
          <div>
            <div className="text-secondary text-xs">Priority</div>
            <div className="text-primary text-sm">{blueprint.priority}</div>
          </div>
          <div className="border-tertiary h-8 border-l" />
          <div>
            <div className="text-secondary text-xs">Version</div>
            <div className="text-primary text-sm">v{blueprint.version}</div>
          </div>
          <div className="border-tertiary h-8 border-l" />
          <div>
            <div className="text-secondary text-xs">Properties</div>
            <div className="text-primary text-sm">{properties.length}</div>
          </div>
          <div className="border-tertiary h-8 border-l" />
          <div>
            <div className="text-secondary text-xs">Filter</div>
            <div className="flex items-center gap-1.5">
              {hasFilter ? (
                <>
                  <Filter className="text-warning size-4" />
                  <span className="text-primary text-sm">Active</span>
                </>
              ) : (
                <span className="text-tertiary text-sm">None</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Conditional Filter detail */}
      {hasFilter && parsedFilter && (
        <div className="border-border bg-card rounded-lg border">
          <div className="border-tertiary border-b px-6 py-4">
            <div className="flex items-center gap-2">
              <Filter className="text-warning size-4" />
              <h3 className="text-primary text-sm font-medium">
                Conditional Filter
              </h3>
              <span className="text-tertiary ml-1 text-xs">
                Only applies to matching entities
              </span>
            </div>
          </div>
          <div className="space-y-4 px-6 py-4">
            {(parsedFilter.project_type?.length ?? 0) > 0 && (
              <div>
                <div
                  className={
                    'text-tertiary mb-2 text-xs font-medium tracking-wider uppercase'
                  }
                >
                  Project Types
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {parsedFilter.project_type.map((pt) => (
                    <Badge
                      className="border-info rounded-md px-2.5 py-1 text-sm"
                      key={pt}
                      variant="info"
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
                    'text-tertiary mb-2 text-xs font-medium tracking-wider uppercase'
                  }
                >
                  Environments
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {parsedFilter.environment.map((env) => (
                    <Badge
                      className="border-success rounded-md px-2.5 py-1 text-sm"
                      key={env}
                      variant="success"
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
      <div className="border-border bg-card rounded-lg border">
        <div className="border-tertiary border-b px-6 py-4">
          <h3 className="text-primary text-sm font-medium">
            Schema Properties
          </h3>
        </div>

        {properties.length === 0 ? (
          <div className="text-tertiary py-8 text-center">
            <FileJson className="mx-auto mb-2 size-8 opacity-50" />
            <div>No properties defined</div>
          </div>
        ) : (
          <div className="divide-tertiary divide-y">
            {properties.map((prop) => {
              const IconComponent = TYPE_ICONS[prop.type] || Type
              return (
                <div className="px-6 py-4" key={prop.name}>
                  <div className="flex items-center gap-3">
                    <IconComponent className="text-tertiary size-4 shrink-0" />
                    <code className="bg-secondary text-info rounded px-2 py-1 text-sm font-medium">
                      {prop.name}
                    </code>
                    <Badge variant="secondary">
                      {prop.type}
                      {prop.format ? ` / ${prop.format}` : ''}
                    </Badge>
                    {prop.required && <Badge variant="danger">Required</Badge>}
                  </div>

                  {prop.description && (
                    <p className="text-secondary mt-1.5 ml-7 text-sm">
                      {prop.description}
                    </p>
                  )}

                  {/* Enum values as badges */}
                  {prop.enumValues && prop.enumValues.length > 0 && (
                    <div className="mt-2 ml-7 flex flex-wrap gap-1.5">
                      {prop.enumValues.map((val) => (
                        <Badge
                          className="border-input text-secondary border font-mono"
                          key={val}
                          variant="secondary"
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
                      <div className="mt-2 ml-7 flex flex-wrap gap-4">
                        {activeMaps.map(([name, map]) => (
                          <div key={name}>
                            <span className="text-tertiary text-xs">
                              {name}
                            </span>
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              {Object.entries(map!).map(([key, val]) => (
                                <Badge
                                  className="border-input text-secondary gap-1.5 border font-mono"
                                  key={key}
                                  variant="secondary"
                                >
                                  {isColorType(name) ? (
                                    <>
                                      <span
                                        className="inline-block size-2 shrink-0 rounded-full"
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
                    <div className="mt-2 ml-7 flex flex-wrap gap-4">
                      {prop.defaultValue !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-tertiary text-xs">Default</span>
                          <code className="bg-secondary text-primary rounded px-1.5 py-0.5 text-xs">
                            {prop.defaultValue}
                          </code>
                        </div>
                      )}
                      {prop.minimum !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-tertiary text-xs">Min</span>
                          <code className="bg-secondary text-primary rounded px-1.5 py-0.5 text-xs">
                            {prop.minimum}
                          </code>
                        </div>
                      )}
                      {prop.maximum !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-tertiary text-xs">Max</span>
                          <code className="bg-secondary text-primary rounded px-1.5 py-0.5 text-xs">
                            {prop.maximum}
                          </code>
                        </div>
                      )}
                      {prop.minLength !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-tertiary text-xs">
                            Min length
                          </span>
                          <code className="bg-secondary text-primary rounded px-1.5 py-0.5 text-xs">
                            {prop.minLength}
                          </code>
                        </div>
                      )}
                      {prop.maxLength !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-tertiary text-xs">
                            Max length
                          </span>
                          <code className="bg-secondary text-primary rounded px-1.5 py-0.5 text-xs">
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
      <div className="border-border bg-card rounded-lg border">
        <button
          className={`hover:bg-secondary flex w-full items-center gap-2 px-6 py-4 text-left ${rawSchemaOpen ? 'border-tertiary border-b' : ''}`}
          onClick={() => setRawSchemaOpen(!rawSchemaOpen)}
        >
          {rawSchemaOpen ? (
            <ChevronDown className="text-tertiary size-4" />
          ) : (
            <ChevronRight className="text-tertiary size-4" />
          )}
          <h3 className="text-primary text-sm font-medium">Raw JSON Schema</h3>
          <span className="text-tertiary text-xs">
            {raw.split('\n').length} lines
          </span>
        </button>
        {rawSchemaOpen && (
          <pre className="text-primary overflow-x-auto px-6 py-4 font-mono text-sm leading-relaxed">
            {raw}
          </pre>
        )}
      </div>
    </div>
  )
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
      colorAge: xUi?.['color-age'] as Record<string, string> | undefined,
      colorMap: xUi?.['color-map'] as Record<string, string> | undefined,
      colorRange: xUi?.['color-range'] as Record<string, string> | undefined,
      defaultValue: ps.default !== undefined ? String(ps.default) : undefined,
      description: ps.description as string | undefined,
      enumValues: ps.enum as string[] | undefined,
      format: ps.format as string | undefined,
      iconAge: xUi?.['icon-age'] as Record<string, string> | undefined,
      iconMap: xUi?.['icon-map'] as Record<string, string> | undefined,
      iconRange: xUi?.['icon-range'] as Record<string, string> | undefined,
      id: name,
      maximum: ps.maximum as number | undefined,
      maxLength: ps.maxLength as number | undefined,
      minimum: ps.minimum as number | undefined,
      minLength: ps.minLength as number | undefined,
      name,
      required: required.includes(name),
      type: (ps.type as SchemaProperty['type']) || 'string',
    })
  }

  return { properties, raw }
}

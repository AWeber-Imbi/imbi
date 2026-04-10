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
import { getBlueprint } from '@/api/endpoints'
import { getTypeBadgeClasses } from '../BlueprintManagement'
import { parseFilterFromBlueprint } from '@/lib/utils'
import type { SchemaProperty } from '@/types'

interface BlueprintDetailProps {
  blueprintKey: { type: string; slug: string }
  blueprintTypes: string[]
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
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
  isDarkMode,
}: BlueprintDetailProps) {
  const [rawSchemaOpen, setRawSchemaOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const {
    data: blueprint,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['blueprint', blueprintKey.type, blueprintKey.slug],
    queryFn: () => getBlueprint(blueprintKey.type, blueprintKey.slug),
  })

  if (isLoading) {
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

  if (error || !blueprint) {
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
        <Button
          variant="outline"
          onClick={onBack}
          className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Blueprint info card */}
      <div
        className={`rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        {/* Title row */}
        <div
          className={`flex items-start justify-between border-b px-6 py-5 ${
            isDarkMode ? 'border-gray-700' : 'border-gray-200'
          }`}
        >
          <div className="flex items-center gap-3">
            <div
              className={`rounded-lg p-2 ${isDarkMode ? 'bg-blue-900/30' : 'bg-blue-100'}`}
            >
              <FileJson
                className={`h-6 w-6 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`}
              />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2
                  className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  {blueprint.name}
                </h2>
                <span
                  className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${getTypeBadgeClasses(blueprint.kind === 'relationship' ? 'relationship' : blueprint.type || '', blueprintTypes, isDarkMode)}`}
                >
                  {blueprint.kind === 'relationship'
                    ? `${blueprint.source ?? '?'} → ${blueprint.target ?? '?'} (${blueprint.edge ?? '?'})`
                    : blueprint.type}
                </span>
              </div>
              <p
                className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {blueprint.description || 'No description'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={handleCopy}
              className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
            >
              {copied ? (
                <Check className="mr-2 h-4 w-4 text-green-500" />
              ) : (
                <Copy className="mr-2 h-4 w-4" />
              )}
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button
              onClick={onEdit}
              className="bg-amber-border text-white hover:bg-amber-border-strong"
            >
              <Edit2 className="mr-2 h-4 w-4" />
              Edit Blueprint
            </Button>
          </div>
        </div>

        {/* Metadata row */}
        <div className="flex flex-wrap items-center gap-6 px-6 py-4">
          <div>
            <div
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Slug
            </div>
            <div
              className={`font-mono text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
            >
              {blueprint.slug}
            </div>
          </div>
          <div
            className={`h-8 border-l ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
          />
          <div>
            <div
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Enabled
            </div>
            <div className="flex items-center gap-1.5">
              {blueprint.enabled ? (
                <>
                  <CheckCircle className="h-4 w-4 text-green-500" />
                  <span
                    className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                  >
                    Yes
                  </span>
                </>
              ) : (
                <>
                  <XCircle className="h-4 w-4 text-gray-400" />
                  <span
                    className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                  >
                    No
                  </span>
                </>
              )}
            </div>
          </div>
          <div
            className={`h-8 border-l ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
          />
          <div>
            <div
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Priority
            </div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
            >
              {blueprint.priority}
            </div>
          </div>
          <div
            className={`h-8 border-l ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
          />
          <div>
            <div
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Version
            </div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
            >
              v{blueprint.version}
            </div>
          </div>
          <div
            className={`h-8 border-l ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
          />
          <div>
            <div
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Properties
            </div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
            >
              {properties.length}
            </div>
          </div>
          <div
            className={`h-8 border-l ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
          />
          <div>
            <div
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Filter
            </div>
            <div className="flex items-center gap-1.5">
              {hasFilter ? (
                <>
                  <Filter
                    className={`h-4 w-4 ${isDarkMode ? 'text-amber-400' : 'text-amber-600'}`}
                  />
                  <span
                    className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                  >
                    Active
                  </span>
                </>
              ) : (
                <span
                  className={`text-sm ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                >
                  None
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Conditional Filter detail */}
      {hasFilter && parsedFilter && (
        <div
          className={`rounded-lg border ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <div
            className={`border-b px-6 py-4 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
          >
            <div className="flex items-center gap-2">
              <Filter
                className={`h-4 w-4 ${isDarkMode ? 'text-amber-400' : 'text-amber-600'}`}
              />
              <h3
                className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                Conditional Filter
              </h3>
              <span
                className={`ml-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                Only applies to matching entities
              </span>
            </div>
          </div>
          <div className="space-y-4 px-6 py-4">
            {(parsedFilter.project_type?.length ?? 0) > 0 && (
              <div>
                <div
                  className={`mb-2 text-xs font-medium uppercase tracking-wider ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                >
                  Project Types
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {parsedFilter.project_type.map((pt) => (
                    <span
                      key={pt}
                      className={`inline-flex items-center rounded-md border px-2.5 py-1 text-sm ${
                        isDarkMode
                          ? 'border-blue-800/50 bg-blue-900/20 text-blue-400'
                          : 'border-blue-200 bg-blue-50 text-blue-700'
                      }`}
                    >
                      {pt}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {(parsedFilter.environment?.length ?? 0) > 0 && (
              <div>
                <div
                  className={`mb-2 text-xs font-medium uppercase tracking-wider ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                >
                  Environments
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {parsedFilter.environment.map((env) => (
                    <span
                      key={env}
                      className={`inline-flex items-center rounded-md border px-2.5 py-1 text-sm ${
                        isDarkMode
                          ? 'border-green-800/50 bg-green-900/20 text-green-400'
                          : 'border-green-200 bg-green-50 text-green-700'
                      }`}
                    >
                      {env}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Schema Properties */}
      <div
        className={`rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <div
          className={`border-b px-6 py-4 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <h3
            className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Schema Properties
          </h3>
        </div>

        {properties.length === 0 ? (
          <div
            className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
          >
            <FileJson className="mx-auto mb-2 h-8 w-8 opacity-50" />
            <div>No properties defined</div>
          </div>
        ) : (
          <div
            className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}
          >
            {properties.map((prop) => {
              const IconComponent = TYPE_ICONS[prop.type] || Type
              return (
                <div key={prop.name} className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <IconComponent
                      className={`h-4 w-4 flex-shrink-0 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                    />
                    <code
                      className={`rounded px-2 py-1 text-sm font-medium ${
                        isDarkMode
                          ? 'bg-gray-700 text-blue-400'
                          : 'bg-gray-100 text-[#2A4DD0]'
                      }`}
                    >
                      {prop.name}
                    </code>
                    <span
                      className={`rounded px-2 py-0.5 text-xs ${
                        isDarkMode
                          ? 'bg-gray-700 text-gray-300'
                          : 'bg-gray-200 text-gray-700'
                      }`}
                    >
                      {prop.type}
                      {prop.format ? ` / ${prop.format}` : ''}
                    </span>
                    {prop.required && (
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${
                          isDarkMode
                            ? 'bg-red-900/30 text-red-400'
                            : 'bg-red-100 text-red-700'
                        }`}
                      >
                        Required
                      </span>
                    )}
                  </div>

                  {prop.description && (
                    <p
                      className={`ml-7 mt-1.5 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                    >
                      {prop.description}
                    </p>
                  )}

                  {/* Enum values as badges */}
                  {prop.enumValues && prop.enumValues.length > 0 && (
                    <div className="ml-7 mt-2 flex flex-wrap gap-1.5">
                      {prop.enumValues.map((val) => (
                        <span
                          key={val}
                          className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-xs ${
                            isDarkMode
                              ? 'border-gray-600 bg-gray-700 text-gray-300'
                              : 'border-gray-200 bg-gray-50 text-gray-700'
                          }`}
                        >
                          {val}
                        </span>
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
                    const chipClass = isDarkMode
                      ? 'border-gray-600 bg-gray-700 text-gray-300'
                      : 'border-gray-200 bg-gray-50 text-gray-700'
                    return (
                      <div className="ml-7 mt-2 flex flex-wrap gap-4">
                        {activeMaps.map(([name, map]) => (
                          <div key={name}>
                            <span
                              className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                            >
                              {name}
                            </span>
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              {Object.entries(map!).map(([key, val]) => (
                                <span
                                  key={key}
                                  className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-mono text-xs ${chipClass}`}
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
                                </span>
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
                          <span
                            className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                          >
                            Default
                          </span>
                          <code
                            className={`rounded px-1.5 py-0.5 text-xs ${
                              isDarkMode
                                ? 'bg-gray-700 text-gray-300'
                                : 'bg-gray-100 text-gray-700'
                            }`}
                          >
                            {prop.defaultValue}
                          </code>
                        </div>
                      )}
                      {prop.minimum !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                          >
                            Min
                          </span>
                          <code
                            className={`rounded px-1.5 py-0.5 text-xs ${
                              isDarkMode
                                ? 'bg-gray-700 text-gray-300'
                                : 'bg-gray-100 text-gray-700'
                            }`}
                          >
                            {prop.minimum}
                          </code>
                        </div>
                      )}
                      {prop.maximum !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                          >
                            Max
                          </span>
                          <code
                            className={`rounded px-1.5 py-0.5 text-xs ${
                              isDarkMode
                                ? 'bg-gray-700 text-gray-300'
                                : 'bg-gray-100 text-gray-700'
                            }`}
                          >
                            {prop.maximum}
                          </code>
                        </div>
                      )}
                      {prop.minLength !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                          >
                            Min length
                          </span>
                          <code
                            className={`rounded px-1.5 py-0.5 text-xs ${
                              isDarkMode
                                ? 'bg-gray-700 text-gray-300'
                                : 'bg-gray-100 text-gray-700'
                            }`}
                          >
                            {prop.minLength}
                          </code>
                        </div>
                      )}
                      {prop.maxLength !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                          >
                            Max length
                          </span>
                          <code
                            className={`rounded px-1.5 py-0.5 text-xs ${
                              isDarkMode
                                ? 'bg-gray-700 text-gray-300'
                                : 'bg-gray-100 text-gray-700'
                            }`}
                          >
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
      <div
        className={`rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <button
          onClick={() => setRawSchemaOpen(!rawSchemaOpen)}
          className={`flex w-full items-center gap-2 px-6 py-4 text-left ${
            isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'
          } ${rawSchemaOpen ? (isDarkMode ? 'border-b border-gray-700' : 'border-b border-gray-200') : ''}`}
        >
          {rawSchemaOpen ? (
            <ChevronDown
              className={`h-4 w-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            />
          ) : (
            <ChevronRight
              className={`h-4 w-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            />
          )}
          <h3
            className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Raw JSON Schema
          </h3>
          <span
            className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
          >
            {raw.split('\n').length} lines
          </span>
        </button>
        {rawSchemaOpen && (
          <pre
            className={`overflow-x-auto px-6 py-4 font-mono text-sm leading-relaxed ${
              isDarkMode ? 'text-gray-300' : 'text-gray-800'
            }`}
          >
            {raw}
          </pre>
        )}
      </div>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft, Edit2, FileJson, AlertCircle, CheckCircle, XCircle
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getBlueprint } from '@/api/endpoints'
import { getTypeBadgeClasses } from '../BlueprintManagement'
import type { SchemaProperty } from '@/types'

interface BlueprintDetailProps {
  blueprintKey: { type: string; slug: string }
  blueprintTypes: string[]
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

function parseSchemaProperties(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  schema: any
): { properties: SchemaProperty[]; raw: string } {
  let parsed = schema
  if (typeof schema === 'string') {
    try {
      parsed = JSON.parse(schema)
    } catch {
      return { properties: [], raw: typeof schema === 'string' ? schema : '{}' }
    }
  }

  const raw = JSON.stringify(parsed, null, 2)
  const props = parsed?.properties || {}
  const required = (parsed?.required || []) as string[]
  const properties: SchemaProperty[] = []

  for (const [name, propSchema] of Object.entries(props)) {
    const ps = propSchema as Record<string, unknown>
    properties.push({
      id: name,
      name,
      type: (ps.type as SchemaProperty['type']) || 'string',
      format: ps.format as string | undefined,
      description: ps.description as string | undefined,
      required: required.includes(name),
      defaultValue:
        ps.default !== undefined ? String(ps.default) : undefined,
      enumValues: ps.enum as string[] | undefined,
      minimum: ps.minimum as number | undefined,
      maximum: ps.maximum as number | undefined,
      minLength: ps.minLength as number | undefined,
      maxLength: ps.maxLength as number | undefined,
    })
  }

  return { properties, raw }
}

export function BlueprintDetail({
  blueprintKey,
  blueprintTypes,
  onEdit,
  onBack,
  isDarkMode,
}: BlueprintDetailProps) {
  const { data: blueprint, isLoading, error } = useQuery({
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
        className={`flex items-center gap-3 p-4 rounded-lg border ${
          isDarkMode
            ? 'bg-red-900/20 border-red-700 text-red-400'
            : 'bg-red-50 border-red-200 text-red-700'
        }`}
      >
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load blueprint</div>
          <div className="text-sm mt-1">
            {error instanceof Error ? error.message : 'Blueprint not found'}
          </div>
        </div>
      </div>
    )
  }

  const { properties, raw } = parseSchemaProperties(blueprint.json_schema)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            variant="outline"
            onClick={onBack}
            className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <div className="flex items-center gap-3">
            <div
              className={`p-2 rounded-lg ${isDarkMode ? 'bg-blue-900/30' : 'bg-blue-100'}`}
            >
              <FileJson
                className={`w-6 h-6 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`}
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
                  className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getTypeBadgeClasses(blueprint.type, blueprintTypes, isDarkMode)}`}
                >
                  {blueprint.type}
                </span>
              </div>
              <p
                className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {blueprint.description || 'No description'}
              </p>
            </div>
          </div>
        </div>
        <Button
          onClick={onEdit}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
        >
          <Edit2 className="w-4 h-4 mr-2" />
          Edit Blueprint
        </Button>
      </div>

      {/* Metadata */}
      <div
        className={`flex items-center gap-6 p-4 rounded-lg border ${
          isDarkMode
            ? 'bg-gray-800 border-gray-700'
            : 'bg-white border-gray-200'
        }`}
      >
        <div>
          <div
            className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Slug
          </div>
          <div
            className={`text-sm font-mono ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
          >
            {blueprint.slug}
          </div>
        </div>
        <div
          className={`border-l h-8 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
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
                <CheckCircle className="w-4 h-4 text-green-500" />
                <span
                  className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                >
                  Yes
                </span>
              </>
            ) : (
              <>
                <XCircle className="w-4 h-4 text-gray-400" />
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
          className={`border-l h-8 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
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
          className={`border-l h-8 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
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
          className={`border-l h-8 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
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
      </div>

      {/* Schema Properties */}
      <div
        className={`rounded-lg border ${
          isDarkMode
            ? 'bg-gray-800 border-gray-700'
            : 'bg-white border-gray-200'
        }`}
      >
        <div
          className={`px-6 py-4 border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <h3
            className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Schema Properties
          </h3>
        </div>

        {properties.length === 0 ? (
          <div
            className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
          >
            <FileJson className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <div>No properties defined</div>
          </div>
        ) : (
          <div
            className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}
          >
            {properties.map((prop) => (
              <div key={prop.name} className="px-6 py-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <code
                      className={`px-2 py-1 rounded text-sm font-medium ${
                        isDarkMode
                          ? 'bg-gray-750 text-blue-400'
                          : 'bg-gray-100 text-[#2A4DD0]'
                      }`}
                    >
                      {prop.name}
                    </code>
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        isDarkMode
                          ? 'bg-gray-700 text-gray-300'
                          : 'bg-gray-200 text-gray-700'
                      }`}
                    >
                      {prop.type}
                      {prop.format ? ` (${prop.format})` : ''}
                    </span>
                    {prop.required && (
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${
                          isDarkMode
                            ? 'bg-red-900/30 text-red-400'
                            : 'bg-red-100 text-red-700'
                        }`}
                      >
                        Required
                      </span>
                    )}
                  </div>
                </div>
                {prop.description && (
                  <p
                    className={`mt-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                  >
                    {prop.description}
                  </p>
                )}
                {/* Constraints */}
                <div className="flex flex-wrap gap-3 mt-2">
                  {prop.defaultValue !== undefined && (
                    <span
                      className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                    >
                      Default: {prop.defaultValue}
                    </span>
                  )}
                  {prop.enumValues && prop.enumValues.length > 0 && (
                    <span
                      className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                    >
                      Enum: {prop.enumValues.join(', ')}
                    </span>
                  )}
                  {prop.minimum !== undefined && (
                    <span
                      className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                    >
                      Min: {prop.minimum}
                    </span>
                  )}
                  {prop.maximum !== undefined && (
                    <span
                      className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                    >
                      Max: {prop.maximum}
                    </span>
                  )}
                  {prop.minLength !== undefined && (
                    <span
                      className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                    >
                      Min length: {prop.minLength}
                    </span>
                  )}
                  {prop.maxLength !== undefined && (
                    <span
                      className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                    >
                      Max length: {prop.maxLength}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Raw JSON Schema */}
      <div
        className={`rounded-lg border ${
          isDarkMode
            ? 'bg-gray-800 border-gray-700'
            : 'bg-white border-gray-200'
        }`}
      >
        <div
          className={`px-6 py-4 border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <h3
            className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Raw JSON Schema
          </h3>
        </div>
        <pre
          className={`px-6 py-4 text-sm font-mono overflow-x-auto ${
            isDarkMode ? 'text-gray-300' : 'text-gray-800'
          }`}
        >
          {raw}
        </pre>
      </div>
    </div>
  )
}

import { useState } from 'react'
import { AlertCircle, Code, List, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { SchemaProperty } from '@/types'
import { type SchemaEditorMode } from './blueprint-schema-utils'
import { BlueprintSchemaPropertyRow } from './BlueprintSchemaPropertyRow'

interface BlueprintSchemaEditorProps {
  editorMode: SchemaEditorMode
  schemaProperties: SchemaProperty[]
  rawSchema: string
  setRawSchema: (value: string) => void
  schemaError: string | null
  setSchemaError: (value: string | null) => void
  handleEditorModeSwitch: (mode: SchemaEditorMode) => void
  validationErrors: Record<string, string>
  touched: Record<string, boolean>
  expandedProps: Set<string>
  setExpandedProps: (value: Set<string>) => void
  uiMapEntries: Record<string, [string, string][]>
  setUiMapEntries: (value: Record<string, [string, string][]>) => void
  addProperty: () => void
  updateProperty: (id: string, updates: Partial<SchemaProperty>) => void
  moveProperty: (index: number, direction: 'up' | 'down') => void
  removeProperty: (id: string) => void
  syncCodeToVisual: (raw: string) => boolean
}

export function BlueprintSchemaEditor({
  editorMode,
  schemaProperties,
  rawSchema,
  setRawSchema,
  schemaError,
  setSchemaError,
  handleEditorModeSwitch,
  validationErrors,
  touched,
  expandedProps,
  setExpandedProps,
  uiMapEntries,
  setUiMapEntries,
  addProperty,
  updateProperty,
  moveProperty,
  removeProperty,
  syncCodeToVisual,
}: BlueprintSchemaEditorProps) {
  const [enumRawText, setEnumRawText] = useState<Record<string, string>>({})

  const toggleExpandProp = (id: string) => {
    const next = new Set(expandedProps)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    setExpandedProps(next)
  }

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-medium text-primary">JSON Schema</h3>
        <div className="flex items-center rounded-lg border border-input">
          <button
            onClick={() => handleEditorModeSwitch('visual')}
            className={`flex items-center gap-1.5 rounded-l-lg px-3 py-1.5 text-sm transition-colors ${
              editorMode === 'visual'
                ? 'bg-info text-info'
                : 'text-secondary hover:text-primary'
            }`}
          >
            <List className="h-3.5 w-3.5" />
            Visual
          </button>
          <button
            onClick={() => handleEditorModeSwitch('code')}
            className={`flex items-center gap-1.5 rounded-r-lg px-3 py-1.5 text-sm transition-colors ${
              editorMode === 'code'
                ? 'bg-info text-info'
                : 'text-secondary hover:text-primary'
            }`}
          >
            <Code className="h-3.5 w-3.5" />
            Code
          </button>
        </div>
      </div>

      {/* Schema Error */}
      {(schemaError || (touched.schema && validationErrors.schema)) && (
        <div className="mb-4 flex items-start gap-2 rounded-lg bg-danger p-3 text-danger">
          <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div className="text-xs">
            {schemaError || validationErrors.schema}
          </div>
        </div>
      )}

      {/* Visual Mode */}
      {editorMode === 'visual' && (
        <div className="space-y-3">
          {schemaProperties.length === 0 ? (
            <div className="py-8 text-center text-tertiary">
              <div>No properties defined</div>
              <div className="mt-1 text-sm">
                Add properties to define the schema
              </div>
            </div>
          ) : (
            schemaProperties.map((prop, index) => {
              const isExpanded = expandedProps.has(prop.id)
              return (
                <BlueprintSchemaPropertyRow
                  key={prop.id}
                  prop={prop}
                  index={index}
                  totalCount={schemaProperties.length}
                  isExpanded={isExpanded}
                  toggleExpandProp={toggleExpandProp}
                  moveProperty={moveProperty}
                  updateProperty={updateProperty}
                  removeProperty={removeProperty}
                  uiMapEntries={uiMapEntries}
                  setUiMapEntries={setUiMapEntries}
                  enumRawText={enumRawText}
                  setEnumRawText={setEnumRawText}
                />
              )
            })
          )}

          <Button onClick={addProperty} variant="outline" className="w-full">
            <Plus className="mr-2 h-4 w-4" />
            Add Property
          </Button>
        </div>
      )}

      {/* Code Mode */}
      {editorMode === 'code' && (
        <textarea
          value={rawSchema}
          onChange={(e) => {
            setRawSchema(e.target.value)
            setSchemaError(null)
          }}
          onBlur={() => syncCodeToVisual(rawSchema)}
          rows={20}
          spellCheck={false}
          className="w-full resize-y rounded-md border border-input bg-secondary px-4 py-3 font-mono text-sm text-primary"
        />
      )}
    </div>
  )
}

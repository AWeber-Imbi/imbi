import { useState } from 'react'

import { AlertCircle, Code, List, Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { SchemaProperty } from '@/types'

import { type SchemaEditorMode } from './blueprint-schema-utils'
import { BlueprintSchemaPropertyRow } from './BlueprintSchemaPropertyRow'

interface BlueprintSchemaEditorProps {
  addProperty: () => void
  editorMode: SchemaEditorMode
  expandedProps: Set<string>
  handleEditorModeSwitch: (mode: SchemaEditorMode) => void
  moveProperty: (index: number, direction: 'down' | 'up') => void
  rawSchema: string
  removeProperty: (id: string) => void
  schemaError: null | string
  schemaProperties: SchemaProperty[]
  setExpandedProps: (value: Set<string>) => void
  setRawSchema: (value: string) => void
  setSchemaError: (value: null | string) => void
  setUiMapEntries: (value: Record<string, [string, string][]>) => void
  syncCodeToVisual: (raw: string) => boolean
  touched: Record<string, boolean>
  uiMapEntries: Record<string, [string, string][]>
  updateProperty: (id: string, updates: Partial<SchemaProperty>) => void
  validationErrors: Record<string, string>
}

export function BlueprintSchemaEditor({
  addProperty,
  editorMode,
  expandedProps,
  handleEditorModeSwitch,
  moveProperty,
  rawSchema,
  removeProperty,
  schemaError,
  schemaProperties,
  setExpandedProps,
  setRawSchema,
  setSchemaError,
  setUiMapEntries,
  syncCodeToVisual,
  touched,
  uiMapEntries,
  updateProperty,
  validationErrors,
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
            className={`flex items-center gap-1.5 rounded-l-lg px-3 py-1.5 text-sm transition-colors ${
              editorMode === 'visual'
                ? 'bg-info text-info'
                : 'text-secondary hover:text-primary'
            }`}
            onClick={() => handleEditorModeSwitch('visual')}
          >
            <List className="h-3.5 w-3.5" />
            Visual
          </button>
          <button
            className={`flex items-center gap-1.5 rounded-r-lg px-3 py-1.5 text-sm transition-colors ${
              editorMode === 'code'
                ? 'bg-info text-info'
                : 'text-secondary hover:text-primary'
            }`}
            onClick={() => handleEditorModeSwitch('code')}
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
                  enumRawText={enumRawText}
                  index={index}
                  isExpanded={isExpanded}
                  key={prop.id}
                  moveProperty={moveProperty}
                  prop={prop}
                  removeProperty={removeProperty}
                  setEnumRawText={setEnumRawText}
                  setUiMapEntries={setUiMapEntries}
                  toggleExpandProp={toggleExpandProp}
                  totalCount={schemaProperties.length}
                  uiMapEntries={uiMapEntries}
                  updateProperty={updateProperty}
                />
              )
            })
          )}

          <Button className="w-full" onClick={addProperty} variant="outline">
            <Plus className="mr-2 h-4 w-4" />
            Add Property
          </Button>
        </div>
      )}

      {/* Code Mode */}
      {editorMode === 'code' && (
        <textarea
          className="w-full resize-y rounded-md border border-input bg-secondary px-4 py-3 font-mono text-sm text-primary"
          onBlur={() => syncCodeToVisual(rawSchema)}
          onChange={(e) => {
            setRawSchema(e.target.value)
            setSchemaError(null)
          }}
          rows={20}
          spellCheck={false}
          value={rawSchema}
        />
      )}
    </div>
  )
}

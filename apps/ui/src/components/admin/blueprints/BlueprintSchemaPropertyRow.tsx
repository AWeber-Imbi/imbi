import { ChevronDown, ChevronUp, Trash2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { SchemaProperty } from '@/types'
import { PROPERTY_TYPES, STRING_FORMATS } from './blueprint-schema-utils'
import { BlueprintUiMapEditor } from './BlueprintUiMapEditor'

interface BlueprintSchemaPropertyRowProps {
  prop: SchemaProperty
  index: number
  totalCount: number
  isExpanded: boolean
  toggleExpandProp: (id: string) => void
  moveProperty: (index: number, direction: 'up' | 'down') => void
  updateProperty: (id: string, updates: Partial<SchemaProperty>) => void
  removeProperty: (id: string) => void
  uiMapEntries: Record<string, [string, string][]>
  setUiMapEntries: (value: Record<string, [string, string][]>) => void
  enumRawText: Record<string, string>
  setEnumRawText: (value: Record<string, string>) => void
}

export function BlueprintSchemaPropertyRow({
  prop,
  index,
  totalCount,
  isExpanded,
  toggleExpandProp,
  moveProperty,
  updateProperty,
  removeProperty,
  uiMapEntries,
  setUiMapEntries,
  enumRawText,
  setEnumRawText,
}: BlueprintSchemaPropertyRowProps) {
  return (
    <div className="rounded-lg border border-input bg-secondary">
      {/* Property Row */}
      <div className="flex items-center gap-3 p-3">
        <div className="flex flex-col gap-0.5">
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex">
                  <button
                    type="button"
                    aria-label="Move property up"
                    onClick={() => moveProperty(index, 'up')}
                    disabled={index === 0}
                    className={`rounded p-0.5 ${
                      index === 0
                        ? 'cursor-not-allowed opacity-30'
                        : 'text-secondary hover:bg-secondary'
                    }`}
                  >
                    <ChevronUp className="h-3 w-3" />
                  </button>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>Move up</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex">
                  <button
                    type="button"
                    aria-label="Move property down"
                    onClick={() => moveProperty(index, 'down')}
                    disabled={index === totalCount - 1}
                    className={`rounded p-0.5 ${
                      index === totalCount - 1
                        ? 'cursor-not-allowed opacity-30'
                        : 'text-secondary hover:bg-secondary'
                    }`}
                  >
                    <ChevronDown className="h-3 w-3" />
                  </button>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>Move down</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <Input
          value={prop.name}
          onChange={(e) =>
            updateProperty(prop.id, {
              name: e.target.value,
            })
          }
          placeholder="Property name"
          className="flex-1 font-mono text-sm"
        />

        <select
          value={prop.type}
          onChange={(e) =>
            updateProperty(prop.id, {
              type: e.target.value as SchemaProperty['type'],
            })
          }
          className="w-28 rounded-md border border-input bg-background px-2 py-2 text-sm text-foreground"
        >
          {PROPERTY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <div className="flex items-center gap-1.5">
          <Checkbox
            id={`req-${prop.id}`}
            checked={prop.required}
            onCheckedChange={(checked) =>
              updateProperty(prop.id, {
                required: checked === true,
              })
            }
          />
          <label
            htmlFor={`req-${prop.id}`}
            className={'cursor-pointer select-none text-xs text-secondary'}
          >
            Required
          </label>
        </div>

        <div className="flex items-center gap-1.5">
          <Checkbox
            id={`editable-${prop.id}`}
            checked={prop.editable !== false}
            onCheckedChange={(checked) =>
              updateProperty(prop.id, {
                editable: checked === true ? undefined : false,
              })
            }
          />
          <label
            htmlFor={`editable-${prop.id}`}
            className={'cursor-pointer select-none text-xs text-secondary'}
          >
            Editable
          </label>
        </div>

        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={
                  isExpanded
                    ? 'Collapse advanced options'
                    : 'Expand advanced options'
                }
                onClick={() => toggleExpandProp(prop.id)}
                className="rounded p-1.5 text-xs text-secondary hover:bg-secondary"
              >
                {isExpanded ? (
                  <ChevronUp className="h-3.5 w-3.5" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5" />
                )}
              </button>
            </TooltipTrigger>
            <TooltipContent>
              <p>Advanced options</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label="Remove property"
                onClick={() => removeProperty(prop.id)}
                className="rounded p-1.5 text-danger hover:bg-danger"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent>
              <p>Remove property</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      {/* Advanced Options */}
      {isExpanded && (
        <div className="space-y-3 border-t border-secondary px-3 pb-3 pt-2">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-secondary">
                Description
              </label>
              <Input
                value={prop.description || ''}
                onChange={(e) =>
                  updateProperty(prop.id, {
                    description: e.target.value || undefined,
                  })
                }
                placeholder="Property description"
                className="text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-secondary">
                Default Value
              </label>
              <Input
                value={prop.defaultValue || ''}
                onChange={(e) =>
                  updateProperty(prop.id, {
                    defaultValue: e.target.value || undefined,
                  })
                }
                placeholder="Default value"
                className="text-sm"
              />
            </div>
          </div>

          {prop.type === 'string' && (
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="mb-1 block text-xs text-secondary">
                  Format
                </label>
                <select
                  value={prop.format || ''}
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      format: e.target.value || undefined,
                    })
                  }
                  className="w-full rounded-md border border-input bg-background px-2 py-2 text-sm text-foreground"
                >
                  {STRING_FORMATS.map((f) => (
                    <option key={f} value={f}>
                      {f || '(none)'}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-secondary">
                  Min Length
                </label>
                <Input
                  type="number"
                  value={prop.minLength ?? ''}
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      minLength: e.target.value
                        ? parseInt(e.target.value, 10)
                        : undefined,
                    })
                  }
                  className="text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-secondary">
                  Max Length
                </label>
                <Input
                  type="number"
                  value={prop.maxLength ?? ''}
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      maxLength: e.target.value
                        ? parseInt(e.target.value, 10)
                        : undefined,
                    })
                  }
                  className="text-sm"
                />
              </div>
            </div>
          )}

          {(prop.type === 'integer' || prop.type === 'number') && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs text-secondary">
                  Minimum
                </label>
                <Input
                  type="number"
                  value={prop.minimum ?? ''}
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      minimum: e.target.value
                        ? Number(e.target.value)
                        : undefined,
                    })
                  }
                  className="text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-secondary">
                  Maximum
                </label>
                <Input
                  type="number"
                  value={prop.maximum ?? ''}
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      maximum: e.target.value
                        ? Number(e.target.value)
                        : undefined,
                    })
                  }
                  className="text-sm"
                />
              </div>
            </div>
          )}

          <div>
            <label className="mb-1 block text-xs text-secondary">
              Enum Values (comma-separated)
            </label>
            <Input
              value={enumRawText[prop.id] ?? prop.enumValues?.join(', ') ?? ''}
              onChange={(e) =>
                setEnumRawText({
                  ...enumRawText,
                  [prop.id]: e.target.value,
                })
              }
              onBlur={() => {
                const raw = enumRawText[prop.id]
                if (raw !== undefined) {
                  const parsed = raw
                    ? raw
                        .split(',')
                        .map((v) => v.trim())
                        .filter(Boolean)
                    : undefined
                  updateProperty(prop.id, {
                    enumValues:
                      parsed && parsed.length > 0 ? parsed : undefined,
                  })
                  const next = { ...enumRawText }
                  delete next[prop.id]
                  setEnumRawText(next)
                }
              }}
              placeholder="e.g. small, medium, large"
              className="text-sm"
            />
          </div>

          {/* UI Maps */}
          {[
            {
              mapType: 'colorMap' as const,
              label: 'Color Map',
              keyPh: 'value',
              valPh: 'e.g. green',
              defaultVal: 'green',
              isColor: true,
            },
            {
              mapType: 'iconMap' as const,
              label: 'Icon Map',
              keyPh: 'value',
              valPh: 'e.g. circle-check-big',
              defaultVal: '',
              isColor: false,
            },
            {
              mapType: 'colorRange' as const,
              label: 'Color Range',
              keyPh: 'e.g. >=90',
              valPh: 'e.g. green',
              defaultVal: 'green',
              isColor: true,
            },
            {
              mapType: 'iconRange' as const,
              label: 'Icon Range',
              keyPh: 'e.g. >=90',
              valPh: 'e.g. check-circle',
              defaultVal: '',
              isColor: false,
            },
            {
              mapType: 'colorAge' as const,
              label: 'Color Age',
              keyPh: 'e.g. >30d',
              valPh: 'e.g. red',
              defaultVal: 'red',
              isColor: true,
            },
            {
              mapType: 'iconAge' as const,
              label: 'Icon Age',
              keyPh: 'e.g. >30d',
              valPh: 'e.g. alert-triangle',
              defaultVal: '',
              isColor: false,
            },
          ].map(
            ({
              mapType,
              label: mapLabel,
              keyPh,
              valPh,
              defaultVal,
              isColor,
            }) => {
              const stateKey = `${mapType}:${prop.id}`
              const entries = uiMapEntries[stateKey] ?? []
              const commit = (next: [string, string][]) => {
                const map = Object.fromEntries(
                  next.filter(([k]) => k.trim() !== ''),
                )
                updateProperty(prop.id, {
                  [mapType]: Object.keys(map).length > 0 ? map : undefined,
                })
              }
              const setEntries = (next: [string, string][]) => {
                setUiMapEntries({
                  ...uiMapEntries,
                  [stateKey]: next,
                })
              }
              return (
                <BlueprintUiMapEditor
                  key={mapType}
                  mapType={mapType}
                  label={mapLabel}
                  keyPh={keyPh}
                  valPh={valPh}
                  defaultVal={defaultVal}
                  isColor={isColor}
                  entries={entries}
                  setEntries={setEntries}
                  commit={commit}
                />
              )
            },
          )}
        </div>
      )}
    </div>
  )
}

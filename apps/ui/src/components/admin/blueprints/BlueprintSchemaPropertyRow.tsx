import { ChevronDown, ChevronUp, Trash2 } from 'lucide-react'

import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { SchemaProperty } from '@/types'

import {
  ARRAY_ITEM_TYPES,
  PROPERTY_TYPES,
  STRING_FORMATS,
} from './blueprint-schema-utils'
import { BlueprintUiMapEditor } from './BlueprintUiMapEditor'

interface BlueprintSchemaPropertyRowProps {
  enumRawText: Record<string, string>
  index: number
  isExpanded: boolean
  moveProperty: (index: number, direction: 'down' | 'up') => void
  prop: SchemaProperty
  removeProperty: (id: string) => void
  setEnumRawText: (value: Record<string, string>) => void
  setUiMapEntries: (value: Record<string, [string, string][]>) => void
  toggleExpandProp: (id: string) => void
  totalCount: number
  uiMapEntries: Record<string, [string, string][]>
  updateProperty: (id: string, updates: Partial<SchemaProperty>) => void
}

export function BlueprintSchemaPropertyRow({
  enumRawText,
  index,
  isExpanded,
  moveProperty,
  prop,
  removeProperty,
  setEnumRawText,
  setUiMapEntries,
  toggleExpandProp,
  totalCount,
  uiMapEntries,
  updateProperty,
}: BlueprintSchemaPropertyRowProps) {
  return (
    <div className="border-input bg-secondary rounded-lg border">
      {/* Property Row */}
      <div className="flex items-center gap-3 p-3">
        <div className="flex flex-col gap-0.5">
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex">
                  <button
                    aria-label="Move property up"
                    className={`rounded p-0.5 ${
                      index === 0
                        ? 'cursor-not-allowed opacity-30'
                        : 'text-secondary hover:bg-secondary'
                    }`}
                    disabled={index === 0}
                    onClick={() => moveProperty(index, 'up')}
                    type="button"
                  >
                    <ChevronUp className="size-3" />
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
                    aria-label="Move property down"
                    className={`rounded p-0.5 ${
                      index === totalCount - 1
                        ? 'cursor-not-allowed opacity-30'
                        : 'text-secondary hover:bg-secondary'
                    }`}
                    disabled={index === totalCount - 1}
                    onClick={() => moveProperty(index, 'down')}
                    type="button"
                  >
                    <ChevronDown className="size-3" />
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
          className="flex-1 font-mono text-sm"
          onChange={(e) =>
            updateProperty(prop.id, {
              name: e.target.value,
            })
          }
          placeholder="Property name"
          value={prop.name}
        />

        <select
          className="border-input bg-background text-foreground w-28 rounded-md border px-2 py-2 text-sm"
          onChange={(e) =>
            updateProperty(prop.id, {
              type: e.target.value as SchemaProperty['type'],
            })
          }
          value={prop.type}
        >
          {PROPERTY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <div className="flex items-center gap-1.5">
          <Checkbox
            checked={prop.required}
            id={`req-${prop.id}`}
            onCheckedChange={(checked) =>
              updateProperty(prop.id, {
                required: checked === true,
              })
            }
          />
          <label
            className={'text-secondary cursor-pointer text-xs select-none'}
            htmlFor={`req-${prop.id}`}
          >
            Required
          </label>
        </div>

        <div className="flex items-center gap-1.5">
          <Checkbox
            checked={prop.editable !== false}
            id={`editable-${prop.id}`}
            onCheckedChange={(checked) =>
              updateProperty(prop.id, {
                editable: checked === true ? undefined : false,
              })
            }
          />
          <label
            className={'text-secondary cursor-pointer text-xs select-none'}
            htmlFor={`editable-${prop.id}`}
          >
            Editable
          </label>
        </div>

        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                aria-label={
                  isExpanded
                    ? 'Collapse advanced options'
                    : 'Expand advanced options'
                }
                className="text-secondary hover:bg-secondary rounded p-1.5 text-xs"
                onClick={() => toggleExpandProp(prop.id)}
                type="button"
              >
                {isExpanded ? (
                  <ChevronUp className="size-3.5" />
                ) : (
                  <ChevronDown className="size-3.5" />
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
                aria-label="Remove property"
                className="text-danger hover:bg-danger rounded p-1.5"
                onClick={() => removeProperty(prop.id)}
                type="button"
              >
                <Trash2 className="size-3.5" />
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
        <div className="border-secondary space-y-3 border-t px-3 pt-2 pb-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-secondary mb-1 block text-xs">
                Description
              </label>
              <Input
                className="text-sm"
                onChange={(e) =>
                  updateProperty(prop.id, {
                    description: e.target.value || undefined,
                  })
                }
                placeholder="Property description"
                value={prop.description || ''}
              />
            </div>
            <div>
              <label className="text-secondary mb-1 block text-xs">
                Default Value
              </label>
              <Input
                className="text-sm"
                onChange={(e) =>
                  updateProperty(prop.id, {
                    defaultValue: e.target.value || undefined,
                  })
                }
                placeholder="Default value"
                value={prop.defaultValue || ''}
              />
            </div>
          </div>

          {prop.type === 'string' && (
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-secondary mb-1 block text-xs">
                  Format
                </label>
                <select
                  className="border-input bg-background text-foreground w-full rounded-md border px-2 py-2 text-sm"
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      format: e.target.value || undefined,
                    })
                  }
                  value={prop.format || ''}
                >
                  {STRING_FORMATS.map((f) => (
                    <option key={f} value={f}>
                      {f || '(none)'}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-secondary mb-1 block text-xs">
                  Min Length
                </label>
                <Input
                  className="text-sm"
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      minLength: e.target.value
                        ? parseInt(e.target.value, 10)
                        : undefined,
                    })
                  }
                  type="number"
                  value={prop.minLength ?? ''}
                />
              </div>
              <div>
                <label className="text-secondary mb-1 block text-xs">
                  Max Length
                </label>
                <Input
                  className="text-sm"
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      maxLength: e.target.value
                        ? parseInt(e.target.value, 10)
                        : undefined,
                    })
                  }
                  type="number"
                  value={prop.maxLength ?? ''}
                />
              </div>
            </div>
          )}

          {prop.type === 'array' && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-secondary mb-1 block text-xs">
                  Items Type
                </label>
                <select
                  className="border-input bg-background text-foreground w-full rounded-md border px-2 py-2 text-sm"
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      itemsType: e.target.value as SchemaProperty['itemsType'],
                    })
                  }
                  value={prop.itemsType ?? 'string'}
                >
                  {ARRAY_ITEM_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-secondary mb-1 block text-xs">
                  Items Enum (comma-separated)
                </label>
                <Input
                  className="text-sm"
                  onBlur={() => {
                    const stateKey = `items:${prop.id}`
                    const raw = enumRawText[stateKey]
                    if (raw !== undefined) {
                      const parsed = raw
                        ? raw
                            .split(',')
                            .map((v) => v.trim())
                            .filter(Boolean)
                        : undefined
                      updateProperty(prop.id, {
                        itemsEnumValues:
                          parsed && parsed.length > 0 ? parsed : undefined,
                      })
                      const next = { ...enumRawText }
                      delete next[stateKey]
                      setEnumRawText(next)
                    }
                  }}
                  onChange={(e) =>
                    setEnumRawText({
                      ...enumRawText,
                      [`items:${prop.id}`]: e.target.value,
                    })
                  }
                  placeholder="e.g. red, green, blue"
                  value={
                    enumRawText[`items:${prop.id}`] ??
                    prop.itemsEnumValues?.join(', ') ??
                    ''
                  }
                />
              </div>
            </div>
          )}

          {(prop.type === 'integer' || prop.type === 'number') && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-secondary mb-1 block text-xs">
                  Minimum
                </label>
                <Input
                  className="text-sm"
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      minimum: e.target.value
                        ? Number(e.target.value)
                        : undefined,
                    })
                  }
                  type="number"
                  value={prop.minimum ?? ''}
                />
              </div>
              <div>
                <label className="text-secondary mb-1 block text-xs">
                  Maximum
                </label>
                <Input
                  className="text-sm"
                  onChange={(e) =>
                    updateProperty(prop.id, {
                      maximum: e.target.value
                        ? Number(e.target.value)
                        : undefined,
                    })
                  }
                  type="number"
                  value={prop.maximum ?? ''}
                />
              </div>
            </div>
          )}

          <div>
            <label className="text-secondary mb-1 block text-xs">
              Enum Values (comma-separated)
            </label>
            <Input
              className="text-sm"
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
              onChange={(e) =>
                setEnumRawText({
                  ...enumRawText,
                  [prop.id]: e.target.value,
                })
              }
              placeholder="e.g. small, medium, large"
              value={enumRawText[prop.id] ?? prop.enumValues?.join(', ') ?? ''}
            />
          </div>

          {/* UI Maps */}
          {[
            {
              defaultVal: 'green',
              isColor: true,
              keyPh: 'value',
              label: 'Color Map',
              mapType: 'colorMap' as const,
              valPh: 'e.g. green',
            },
            {
              defaultVal: '',
              isColor: false,
              keyPh: 'value',
              label: 'Icon Map',
              mapType: 'iconMap' as const,
              valPh: 'e.g. circle-check-big',
            },
            {
              defaultVal: 'green',
              isColor: true,
              keyPh: 'e.g. >=90',
              label: 'Color Range',
              mapType: 'colorRange' as const,
              valPh: 'e.g. green',
            },
            {
              defaultVal: '',
              isColor: false,
              keyPh: 'e.g. >=90',
              label: 'Icon Range',
              mapType: 'iconRange' as const,
              valPh: 'e.g. check-circle',
            },
            {
              defaultVal: 'red',
              isColor: true,
              keyPh: 'e.g. >30d',
              label: 'Color Age',
              mapType: 'colorAge' as const,
              valPh: 'e.g. red',
            },
            {
              defaultVal: '',
              isColor: false,
              keyPh: 'e.g. >30d',
              label: 'Icon Age',
              mapType: 'iconAge' as const,
              valPh: 'e.g. alert-triangle',
            },
          ].map(
            ({
              defaultVal,
              isColor,
              keyPh,
              label: mapLabel,
              mapType,
              valPh,
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
                  commit={commit}
                  defaultVal={defaultVal}
                  entries={entries}
                  isColor={isColor}
                  key={mapType}
                  keyPh={keyPh}
                  label={mapLabel}
                  mapType={mapType}
                  setEntries={setEntries}
                  valPh={valPh}
                />
              )
            },
          )}
        </div>
      )}
    </div>
  )
}

import Ajv from 'ajv'
import type { SchemaProperty } from '@/types'

export const ajv = new Ajv()

// Known relationships keyed by "Source:Target"
export const RELATIONSHIP_MAP: Record<string, string[]> = {
  'Project:Environment': ['DEPLOYED_IN'],
  'Project:ProjectType': ['TYPE'],
  'Project:Team': ['OWNED_BY'],
  'Project:Project': ['DEPENDS_ON'],
  'Team:Organization': ['BELONGS_TO'],
  'Environment:Organization': ['BELONGS_TO'],
  'ProjectType:Organization': ['BELONGS_TO'],
  'ThirdPartyService:Organization': ['BELONGS_TO'],
}

export function getRelationshipTypes(source: string, target: string): string[] {
  if (!source || !target) {
    // Show all unique types when pair not yet selected
    const all = new Set<string>()
    for (const types of Object.values(RELATIONSHIP_MAP)) {
      for (const t of types) all.add(t)
    }
    return Array.from(all).sort()
  }
  return RELATIONSHIP_MAP[`${source}:${target}`] || []
}

export function toTitleCase(value: string): string {
  return value
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export const PROPERTY_TYPES: SchemaProperty['type'][] = [
  'string',
  'integer',
  'number',
  'boolean',
  'array',
  'object',
]

export const STRING_FORMATS = [
  '',
  'date',
  'date-time',
  'email',
  'uri',
  'uri-reference',
  'hostname',
  'ipv4',
  'ipv6',
  'uuid',
]

export function toSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 9)
}

export function buildJsonSchema(
  properties: SchemaProperty[],
): Record<string, unknown> {
  const schema: Record<string, unknown> = {
    type: 'object',
    properties: {} as Record<string, unknown>,
  }
  const required: string[] = []
  const props = schema.properties as Record<string, Record<string, unknown>>

  for (const prop of properties) {
    const propSchema: Record<string, unknown> = { type: prop.type }

    if (prop.description) propSchema.description = prop.description
    if (prop.format) propSchema.format = prop.format
    if (prop.defaultValue !== undefined && prop.defaultValue !== '') {
      if (prop.type === 'integer' || prop.type === 'number') {
        propSchema.default = Number(prop.defaultValue)
      } else if (prop.type === 'boolean') {
        propSchema.default = prop.defaultValue === 'true'
      } else {
        propSchema.default = prop.defaultValue
      }
    }
    if (prop.enumValues && prop.enumValues.length > 0) {
      propSchema.enum = prop.enumValues
    }
    if (prop.minimum !== undefined) propSchema.minimum = prop.minimum
    if (prop.maximum !== undefined) propSchema.maximum = prop.maximum
    if (prop.minLength !== undefined) propSchema.minLength = prop.minLength
    if (prop.maxLength !== undefined) propSchema.maxLength = prop.maxLength

    if (prop.type === 'array') {
      propSchema.items = { type: 'string' }
    }

    const uiEntries: [string, Record<string, string> | undefined][] = [
      ['color-map', prop.colorMap],
      ['icon-map', prop.iconMap],
      ['color-range', prop.colorRange],
      ['icon-range', prop.iconRange],
      ['color-age', prop.colorAge],
      ['icon-age', prop.iconAge],
    ]
    const xUiObj: Record<string, unknown> = {}
    if (prop.editable === false) xUiObj['editable'] = false
    for (const [key, map] of uiEntries) {
      if (map && Object.keys(map).length > 0) xUiObj[key] = map
    }
    if (Object.keys(xUiObj).length > 0) {
      propSchema['x-ui'] = xUiObj
    }

    props[prop.name] = propSchema
    if (prop.required) required.push(prop.name)
  }

  if (required.length > 0) schema.required = required
  return schema
}

export function schemaToProperties(
  schema: Record<string, unknown>,
): SchemaProperty[] {
  const props = (schema.properties || {}) as Record<
    string,
    Record<string, unknown>
  >
  const required = (schema.required || []) as string[]
  const result: SchemaProperty[] = []

  for (const [name, propSchema] of Object.entries(props)) {
    const xUi = propSchema['x-ui'] as Record<string, unknown> | undefined
    result.push({
      id: generateId(),
      name,
      type: (propSchema.type as SchemaProperty['type']) || 'string',
      format: propSchema.format as string | undefined,
      description: propSchema.description as string | undefined,
      required: required.includes(name),
      defaultValue:
        propSchema.default !== undefined
          ? String(propSchema.default)
          : undefined,
      enumValues: propSchema.enum as string[] | undefined,
      minimum: propSchema.minimum as number | undefined,
      maximum: propSchema.maximum as number | undefined,
      minLength: propSchema.minLength as number | undefined,
      maxLength: propSchema.maxLength as number | undefined,
      editable: xUi?.['editable'] === false ? false : undefined,
      colorMap: xUi?.['color-map'] as Record<string, string> | undefined,
      iconMap: xUi?.['icon-map'] as Record<string, string> | undefined,
      colorRange: xUi?.['color-range'] as Record<string, string> | undefined,
      iconRange: xUi?.['icon-range'] as Record<string, string> | undefined,
      colorAge: xUi?.['color-age'] as Record<string, string> | undefined,
      iconAge: xUi?.['icon-age'] as Record<string, string> | undefined,
    })
  }

  return result
}

export type SchemaEditorMode = 'visual' | 'code'

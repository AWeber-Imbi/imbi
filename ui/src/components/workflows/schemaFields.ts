import type { JsonSchema } from './types'

// Turns a step type's `params_schema` into inspector form fields.

/** Live data that a select field takes its options from. */
export type FieldSource =
  | 'environment'
  | 'model'
  | 'project'
  | 'team'
  | 'webhook'

export type ParamField =
  | (FieldBase & {
      kind: 'boolean' | 'json' | 'list' | 'number' | 'recipients' | 'text'
    })
  | (FieldBase & { kind: 'multiline'; mono: boolean })
  | (FieldBase & {
      kind: 'select'
      options: { label: string; value: string }[]
    })
  | (FieldBase & { kind: 'source'; source: FieldSource })

interface FieldBase {
  description?: string
  label: string
  name: string
  required: boolean
}

// Parameters that hold the graph node id (or, for environments, the
// slug) of a live record, by name. They match the W1 step registry.
const SOURCES: Record<string, FieldSource> = {
  environment: 'environment',
  model_id: 'model',
  project_id: 'project',
  webhook_id: 'webhook',
}

const MULTILINE = new Set(['body', 'context', 'filter', 'prompt'])
const MONO = new Set(['filter'])

export function paramFields(schema: JsonSchema): ParamField[] {
  const required = new Set(schema.required ?? [])
  return Object.entries(schema.properties ?? {}).map(([name, raw]) => {
    const prop = resolve(schema, raw)
    // Pydantic titles every property ("Model Id"), so the label comes
    // from the name instead.
    const base: FieldBase = {
      description: prop.description,
      label: humanize(name),
      name,
      required: required.has(name),
    }
    if (SOURCES[name]) return { ...base, kind: 'source', source: SOURCES[name] }
    if (prop.enum) {
      const options = prop.enum.map((v) => ({
        label: humanize(String(v)),
        value: String(v),
      }))
      return { ...base, kind: 'select', options }
    }
    if (prop.type === 'boolean') return { ...base, kind: 'boolean' }
    if (prop.type === 'integer' || prop.type === 'number') {
      return { ...base, kind: 'number' }
    }
    if (prop.type === 'array' && prop.items) {
      const item = resolve(schema, prop.items)
      if (item.type === 'string') return { ...base, kind: 'list' }
      if (item.properties?.kind && item.properties.id) {
        return { ...base, kind: 'recipients' }
      }
    }
    if (prop.type === 'string') {
      if (MULTILINE.has(name)) {
        return { ...base, kind: 'multiline', mono: MONO.has(name) }
      }
      return { ...base, kind: 'text' }
    }
    return { ...base, kind: 'json' }
  })
}

/** One line about a node's params for its canvas card. */
export function paramSummary(params: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [name, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      parts.push(`${value.length} ${name.replace(/_/g, ' ')}`)
    } else if (
      // Ids of live records read as noise on the card.
      (typeof value === 'string' && value.trim() && !name.endsWith('_id')) ||
      typeof value === 'number'
    ) {
      parts.push(String(value).split('\n')[0])
    }
    if (parts.length === 2) break
  }
  return parts.join(' · ')
}

function humanize(name: string): string {
  const words = name.replace(/_id$/, '').replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** Follow a local `$ref`, and take the non-null branch of `X | None`. */
function resolve(root: JsonSchema, prop: JsonSchema): JsonSchema {
  if (prop.$ref) {
    return root.$defs?.[prop.$ref.replace('#/$defs/', '')] ?? prop
  }
  const branch = prop.anyOf?.find((s) => s.type !== 'null')
  return branch ? { ...prop, ...branch, anyOf: undefined } : prop
}

// A resource id is a literal id or one plain reference, as the API's
// validation requires: anything else could render an id of another org.
const PLAIN_REFERENCE =
  /^\{\{\s*[a-z][a-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+\s*\}\}$/
const TEMPLATE_MARKERS = ['{{', '{%', '{#']

export function isIdOrReference(value: string): boolean {
  return (
    !TEMPLATE_MARKERS.some((m) => value.includes(m)) ||
    PLAIN_REFERENCE.test(value)
  )
}

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
  | (FieldBase & { kind: 'boolean' | 'json' | 'list' | 'number' | 'text' })
  | (FieldBase & { kind: 'multiline'; mono: boolean })
  | (FieldBase & { kind: 'select'; options: string[] })
  | (FieldBase & { kind: 'source'; source: FieldSource })

interface FieldBase {
  description?: string
  label: string
  name: string
  required: boolean
}

// Parameters that hold the id or slug of a live record, by name.
const SOURCES: Record<string, FieldSource> = {
  environment: 'environment',
  environment_slug: 'environment',
  model_id: 'model',
  project_id: 'project',
  team_slug: 'team',
  webhook_id: 'webhook',
}

const MULTILINE = new Set(['body', 'filter', 'inputs', 'prompt'])
const MONO = new Set(['filter', 'inputs'])
const UUID =
  /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i

export function paramFields(schema: JsonSchema): ParamField[] {
  const required = new Set(schema.required ?? [])
  return Object.entries(schema.properties ?? {}).map(([name, prop]) => {
    const base: FieldBase = {
      description: prop.description,
      label: prop.title ?? humanize(name),
      name,
      required: required.has(name),
    }
    const type = Array.isArray(prop.type)
      ? prop.type.find((t) => t !== 'null')
      : prop.type
    if (SOURCES[name]) return { ...base, kind: 'source', source: SOURCES[name] }
    if (prop.enum) {
      return { ...base, kind: 'select', options: prop.enum.map(String) }
    }
    if (type === 'boolean') return { ...base, kind: 'boolean' }
    if (type === 'integer' || type === 'number') {
      return { ...base, kind: 'number' }
    }
    if (type === 'array' && prop.items?.type === 'string') {
      return { ...base, kind: 'list' }
    }
    if (type === 'string') {
      if (prop.format === 'multiline' || MULTILINE.has(name)) {
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
      (typeof value === 'string' && value.trim() && !UUID.test(value)) ||
      typeof value === 'number'
    ) {
      parts.push(String(value).split('\n')[0])
    }
    if (parts.length === 2) break
  }
  return parts.join(' · ')
}

function humanize(name: string): string {
  const words = name.replace(/_id$|_slug$/, '').replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

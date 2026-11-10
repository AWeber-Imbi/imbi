/** A field kind that the form can draw: text, or a list of text. */
/** A schema that the form can draw: it has properties. */
export type DrawableSchema = ObjectSchema & {
  properties: Record<string, SchemaField>
}

export interface ObjectSchema {
  properties?: Record<string, SchemaField>
  required?: string[]
}

/** One field of a JSON Schema from a provider type. */
export interface SchemaField {
  anyOf?: { type?: string }[]
  default?: unknown
  description?: string
  items?: { type?: string }
  title?: string
  type?: string
}

export const fieldKind = (field: SchemaField) => {
  const type = field.type ?? field.anyOf?.find((t) => t.type !== 'null')?.type
  if (type === 'string') return 'text'
  if (type === 'array' && field.items?.type === 'string') return 'list'
  return null
}

/** The schema when the form can draw each of its fields, else null. */
export const drawable = (schema: unknown) => {
  const props = (schema as null | ObjectSchema)?.properties
  return props &&
    Object.keys(props).length &&
    Object.values(props).every(fieldKind)
    ? (schema as DrawableSchema)
    : null
}

/** The JSON object in `text`, or null. */
export const jsonObject = (text: string) => {
  try {
    const value: unknown = JSON.parse(text)
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}

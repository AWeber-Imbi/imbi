import { KEY_PATTERN } from './graph'

export const SCALAR_TYPES = ['string', 'integer', 'number', 'boolean'] as const
export const FIELD_TYPES = [...SCALAR_TYPES, 'array', 'object'] as const
export const ITEM_TYPES = [...SCALAR_TYPES, 'object'] as const
export const STRING_FORMATS = [
  'date-time',
  'time',
  'date',
  'duration',
  'email',
  'hostname',
  'uri',
  'ipv4',
  'ipv6',
  'uuid',
] as const

export const MAX_OPTIONAL_FIELDS = 24

/** A template resolves these to methods of the result, not to fields. */
const RESERVED_NAMES = new Set([
  'clear',
  'copy',
  'fromkeys',
  'get',
  'items',
  'keys',
  'pop',
  'popitem',
  'setdefault',
  'update',
  'values',
])

/**
 * A field of an agent step's structured output. A sub-field of an
 * object takes a scalar type and no `items` or `fields`.
 */
export interface OutputField {
  description?: string
  enum?: null | string[]
  fields?: null | OutputField[]
  format?: (typeof STRING_FORMATS)[number] | null
  items?: (typeof ITEM_TYPES)[number] | null
  name: string
  required?: boolean
  type: (typeof FIELD_TYPES)[number]
}

export function blankField(siblings: OutputField[]): OutputField {
  const taken = new Set(siblings.map((field) => field.name))
  let index = siblings.length + 1
  while (taken.has(`field_${index}`)) index++
  return { name: `field_${index}`, required: true, type: 'string' }
}

export function hasSubFields(field: OutputField): boolean {
  return (
    field.type === 'object' ||
    (field.type === 'array' && field.items === 'object')
  )
}

export function isStringValued(field: OutputField): boolean {
  return (field.type === 'array' ? field.items : field.type) === 'string'
}

export function nameError(
  field: OutputField,
  siblings: OutputField[],
): string | undefined {
  if (!KEY_PATTERN.test(field.name)) {
    return 'Use lower case letters, digits, and _, starting with a letter.'
  }
  if (RESERVED_NAMES.has(field.name)) {
    return 'This name is reserved.'
  }
  if (siblings.filter((sibling) => sibling.name === field.name).length > 1) {
    return 'Another field has this name.'
  }
}

export function normalize(field: OutputField): OutputField {
  const { enum: values, fields, format, items, ...rest } = field
  const shaped: OutputField =
    field.type === 'array' ? { ...rest, items: items ?? 'string' } : rest
  const strings = isStringValued(shaped)
  return {
    ...shaped,
    ...(hasSubFields(shaped) && {
      fields: fields?.length ? fields : [blankField([])],
    }),
    ...(strings && !!values?.length && { enum: values }),
    ...(strings && !!format && { format }),
  }
}

export function optionalCount(fields: OutputField[]): number {
  return fields.reduce(
    (count, field) =>
      count +
      (field.required === false ? 1 : 0) +
      optionalCount(field.fields ?? []),
    0,
  )
}

export function typeLabel(field: OutputField): string {
  const base = field.type === 'array' ? `array<${field.items}>` : field.type
  return field.required === false ? `${base} | null` : base
}

import type { ProjectSchemaSectionProperty } from '@/api/endpoints'

export const READ_ONLY_KEYS: ReadonlySet<string> = new Set([
  'created_at',
  'id',
  'updated_at',
])

export type InlineKind =
  | 'array'
  | 'date'
  | 'number'
  | 'select'
  | 'switch'
  | 'text'

export function isFieldEditable(
  key: string,
  def: Pick<ProjectSchemaSectionProperty, 'x-ui'> | Record<string, unknown>,
): boolean {
  if (READ_ONLY_KEYS.has(key)) return false
  const xUi = (def as ProjectSchemaSectionProperty)['x-ui']
  if (xUi && xUi.editable === false) return false
  return true
}

export function pickInlineComponent(
  def: Partial<ProjectSchemaSectionProperty>,
): InlineKind {
  if (def.enum && def.enum.length > 0) return 'select'
  if (def.type === 'array') return 'array'
  if (def.type === 'boolean') return 'switch'
  if (def.format === 'date' || def.format === 'date-time') return 'date'
  if (def.type === 'integer' || def.type === 'number') return 'number'
  return 'text'
}

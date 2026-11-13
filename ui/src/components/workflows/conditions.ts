import type { ReferenceGroup } from './references'

export interface Condition {
  a?: unknown
  b?: unknown
  operator: string
}

interface Fit {
  needs: string
  types: string[]
}

type Side = 'a' | 'b'

export const MAX_CONDITIONS = 10

export const OPERATOR_LABELS: Record<string, string> = {
  contains: 'contains',
  ends_with: 'ends with',
  equals: 'equals',
  greater_or_equal: 'is greater than or equal to',
  greater_than: 'is greater than',
  is_empty: 'is empty',
  is_not_empty: 'is not empty',
  less_or_equal: 'is less than or equal to',
  less_than: 'is less than',
  matches: 'matches (regex)',
  not_contains: 'does not contain',
  not_equals: 'does not equal',
  starts_with: 'starts with',
}

const UNARY = new Set(['is_empty', 'is_not_empty'])

const ANY: Fit = {
  needs: 'any value',
  types: ['string', 'integer', 'number', 'boolean', 'array', 'object'],
}
const SCALAR: Fit = {
  needs: 'a single value',
  types: ['string', 'integer', 'number', 'boolean'],
}
const NUMBER: Fit = { needs: 'a number', types: ['integer', 'number'] }
const TEXT: Fit = { needs: 'text', types: ['string'] }
const TEXT_OR_LIST: Fit = {
  needs: 'text or a list',
  types: ['string', 'array'],
}

const FITS: Record<string, [Fit, Fit]> = {
  contains: [TEXT_OR_LIST, SCALAR],
  ends_with: [TEXT, SCALAR],
  equals: [SCALAR, SCALAR],
  greater_or_equal: [NUMBER, NUMBER],
  greater_than: [NUMBER, NUMBER],
  is_empty: [ANY, ANY],
  is_not_empty: [ANY, ANY],
  less_or_equal: [NUMBER, NUMBER],
  less_than: [NUMBER, NUMBER],
  matches: [TEXT, SCALAR],
  not_contains: [TEXT_OR_LIST, SCALAR],
  not_equals: [SCALAR, SCALAR],
  starts_with: [TEXT, SCALAR],
}

const WHOLE_REFERENCE =
  /^\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}$/

export function conditionWarnings(
  row: Condition,
  groups: ReferenceGroup[],
): string[] {
  const sides: Side[] = isUnary(row.operator) ? ['a'] : ['a', 'b']
  return sides.flatMap((side) => {
    const types = referenceTypes(row[side], groups)
    const needs = mismatch(row.operator, side, types)
    if (!needs) return []
    return [
      `${String(row[side])} is ${types.join(' or ')}, but "${operatorLabel(row.operator)}" needs ${needs}.`,
    ]
  })
}

export function isUnary(operator: string): boolean {
  return UNARY.has(operator)
}

export function mismatch(
  operator: string,
  side: Side,
  types: string[],
): null | string {
  const fit = FITS[operator]?.[side === 'a' ? 0 : 1]
  if (!fit || types.length === 0) return null
  return types.some((type) => fit.types.includes(type)) ? null : fit.needs
}

export function operatorLabel(operator: string): string {
  return OPERATOR_LABELS[operator] ?? operator.replace(/_/g, ' ')
}

export function referenceTypes(
  value: unknown,
  groups: ReferenceGroup[],
): string[] {
  const path =
    typeof value === 'string' ? WHOLE_REFERENCE.exec(value)?.[1] : undefined
  if (!path || path.split('.')[0] === 'trigger') return []
  const reference = groups
    .flatMap((group) => group.references)
    .find((candidate) => candidate.path === path)
  if (!reference) return []
  return reference.type
    .replace(/array<.*?>/g, 'array')
    .split(' | ')
    .filter((type) => type !== 'null' && type !== 'any')
}

import type { PatchOperation } from '@/types'

export type { PatchOperation }

function encodePointerSegment(seg: string): string {
  return seg.replace(/~/g, '~0').replace(/\//g, '~1')
}

function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (a === null || b === null) return false
  if (typeof a !== typeof b) return false
  if (typeof a !== 'object') return false
  if (Array.isArray(a) !== Array.isArray(b)) return false
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false
    return a.every((v, i) => deepEqual(v, b[i]))
  }
  const ao = a as Record<string, unknown>
  const bo = b as Record<string, unknown>
  const keys = new Set([...Object.keys(ao), ...Object.keys(bo)])
  for (const k of keys) {
    if (!deepEqual(ao[k], bo[k])) return false
  }
  return true
}

/**
 * Emit one `replace` op per provided key. Use for "set these fields"
 * mutations that don't need to diff against a prior state.
 */
export function buildReplacePatch(
  updates: Record<string, unknown>,
): PatchOperation[] {
  return Object.entries(updates).map(([key, value]) => ({
    op: 'replace',
    path: `/${encodePointerSegment(key)}`,
    value,
  }))
}

/**
 * Diff two records and emit add/replace/remove ops for keys that differ.
 * `undefined` is treated as absent, matching JSON serialization semantics.
 * By default only the keys present in `after` (or both) are considered;
 * pass `options.fields` to scope explicitly, or `options.ignore` to skip
 * server-managed fields.
 */
export function buildDiffPatch(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
  options: { fields?: string[]; ignore?: string[] } = {},
): PatchOperation[] {
  const { fields, ignore } = options
  const keys = fields ?? [
    ...new Set([...Object.keys(before), ...Object.keys(after)]),
  ]
  const ignoreSet = new Set(ignore ?? [])
  const ops: PatchOperation[] = []
  for (const key of keys) {
    if (ignoreSet.has(key)) continue
    const hasBefore = key in before && before[key] !== undefined
    const hasAfter = key in after && after[key] !== undefined
    const bv = before[key]
    const av = after[key]
    if (!hasAfter && hasBefore) {
      ops.push({ op: 'remove', path: `/${encodePointerSegment(key)}` })
    } else if (hasAfter && !hasBefore) {
      ops.push({
        op: 'add',
        path: `/${encodePointerSegment(key)}`,
        value: av,
      })
    } else if (hasAfter && hasBefore && !deepEqual(bv, av)) {
      ops.push({
        op: 'replace',
        path: `/${encodePointerSegment(key)}`,
        value: av,
      })
    }
  }
  return ops
}

/**
 * Apply JSON Patch operations to a top-level object.
 * Supports only `replace` and `remove` on top-level paths (`/<key>`).
 * Returns a new object; input is not mutated.
 */
export function applyJsonPatch<T extends Record<string, unknown>>(
  doc: T,
  ops: PatchOperation[],
): T {
  let out: Record<string, unknown> = { ...doc }
  for (const op of ops) {
    if (op.op !== 'replace' && op.op !== 'remove') {
      throw new Error(`unsupported op: ${op.op}`)
    }
    const parts = op.path.split('/')
    if (parts.length !== 2 || parts[0] !== '') {
      throw new Error(`only top-level paths supported, got: ${op.path}`)
    }
    const key = decodePointerSegment(parts[1])
    if (op.op === 'replace') {
      out = { ...out, [key]: op.value }
    } else {
      const { [key]: _removed, ...rest } = out
      out = rest
    }
  }
  return out as T
}

function decodePointerSegment(seg: string): string {
  return seg.replace(/~1/g, '/').replace(/~0/g, '~')
}

import type { PatchOperation } from '@/types'

export type { PatchOperation }

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

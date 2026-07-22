import { createPluginEntity, listPluginEntities } from '@/api/endpoints'
import type { PluginEntity, PluginVertexLabel } from '@/types'

/**
 * The first single-field unique index on a vertex label is the
 * operator-facing natural key — the value users paste to identify an
 * entity (e.g. an AWS account id).  Returns ``null`` if the label has
 * no such index.
 */
export const naturalKeyField = (
  vlabel: PluginVertexLabel | undefined,
): null | string => {
  for (const idx of vlabel?.indexes ?? []) {
    if (idx.unique && idx.fields.length === 1) return idx.fields[0]
  }
  return null
}

/**
 * Resolve a ``PluginEntity`` by its natural key, creating one with just
 * the key field populated if no match exists.
 *
 * The lookup-or-create dance is shared by every paste-style edge
 * editor: the user pastes a value, we want a target entity to link to,
 * and we don't want to force a full creation dialog when the missing
 * fields can be backfilled later via the entity admin.
 *
 * Race-safe: if a concurrent request creates the entity between our
 * miss and our POST, we re-list and return the freshly-created row
 * rather than surfacing the duplicate-key error.
 */
export async function findOrCreatePluginEntityByKey(args: {
  existing?: PluginEntity[]
  keyField: string
  label: string
  pluginSlug: string
  value: string
}): Promise<PluginEntity> {
  const { existing, keyField, label, pluginSlug, value } = args
  const found = (existing ?? []).find((t) => t[keyField] === value)
  if (found) return found

  const body: Record<string, unknown> = { name: value }
  body[keyField] = value
  try {
    return await createPluginEntity(pluginSlug, label, body)
  } catch (err) {
    const fresh = await listPluginEntities(pluginSlug, label)
    const racedTo = fresh.find((t) => t[keyField] === value)
    if (racedTo) return racedTo
    throw err
  }
}

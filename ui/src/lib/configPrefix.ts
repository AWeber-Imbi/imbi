/**
 * Resolve `${...}` placeholders left in a configured `path_prefix` by
 * matching the template against the keys the plugin actually returned.
 *
 * Some variables can't be expanded client-side — `${project_type_slug}` may
 * be remapped by an integration-level option we don't have, and
 * `${environment}` varies per row. The resolved keys carry the real values,
 * so a placeholder is filled in when every matching key agrees on it and is
 * left as-is otherwise.
 */
export function resolvePrefixPlaceholders(
  template: string,
  keys: string[],
): string {
  // Odd indexes are placeholder names, even indexes literal text.
  const parts = template.split(/\$\{([^}]+)\}/)
  if (parts.length < 3 || keys.length === 0) return template

  const pattern = new RegExp(
    '^' + parts.map((p, i) => (i % 2 ? '([^/]+)' : escapeRegExp(p))).join(''),
  )
  const seen = parts.filter((_, i) => i % 2 === 1).map(() => new Set<string>())
  for (const key of keys) {
    const match = pattern.exec(key)
    if (!match) continue
    match.slice(1).forEach((value, i) => seen[i].add(value))
  }

  return parts
    .map((part, i) => {
      if (i % 2 === 0) return part
      const values = seen[(i - 1) / 2]
      return values.size === 1 ? [...values][0] : '${' + part + '}'
    })
    .join('')
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

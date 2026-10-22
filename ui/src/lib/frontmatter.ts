import yaml from 'js-yaml'

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/

export interface SplitFrontmatter {
  body: string
  meta: null | Record<string, unknown>
}

export function formatFrontmatterValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.map(formatFrontmatterValue).join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/**
 * Split a leading YAML frontmatter block from markdown. Returns the
 * markdown unchanged with ``meta: null`` when there is no block or the
 * block is not a YAML mapping, so a bad header never breaks rendering.
 */
export function splitFrontmatter(markdown: string): SplitFrontmatter {
  const match = FRONTMATTER.exec(markdown)
  if (!match) return { body: markdown, meta: null }
  let meta: unknown
  try {
    // CORE_SCHEMA keeps dates such as 2026-10-22 as strings.
    meta = yaml.load(match[1], { schema: yaml.CORE_SCHEMA })
  } catch {
    return { body: markdown, meta: null }
  }
  if (
    !meta ||
    typeof meta !== 'object' ||
    Array.isArray(meta) ||
    hasSharedNode(meta, new WeakSet())
  ) {
    return { body: markdown, meta: null }
  }
  return {
    body: markdown.slice(match[0].length),
    meta: meta as Record<string, unknown>,
  }
}

/**
 * True when an object or array occurs more than once, which only a YAML
 * alias can cause. Formatting such a value expands each alias, so a small
 * header can grow exponentially ("billion laughs") or loop on a cycle.
 */
function hasSharedNode(value: unknown, seen: WeakSet<object>): boolean {
  if (!value || typeof value !== 'object') return false
  if (seen.has(value)) return true
  seen.add(value)
  return Object.values(value).some((child) => hasSharedNode(child, seen))
}

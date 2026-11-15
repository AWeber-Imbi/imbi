import type { Nodes } from 'mdast'
import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmFromMarkdown } from 'mdast-util-gfm'
import { gfm } from 'micromark-extension-gfm'

import { formatFrontmatterValue, splitFrontmatter } from '@/lib/frontmatter'

const INLINE = new Set([
  'delete',
  'emphasis',
  'heading',
  'link',
  'linkReference',
  'paragraph',
  'strong',
  'tableCell',
])

/**
 * The text `RichMarkdown` shows once rendered: no syntax, raw HTML as
 * literal text, the frontmatter table's keys and values, a line per block,
 * and a deferred image's button label.
 */
export function markdownText(markdown: string): string {
  const { body, meta } = splitFrontmatter(markdown)
  if (!meta) return parse(body)
  return [
    ...Object.entries(meta).flatMap(([key, value]) => [
      key,
      parse(formatFrontmatterValue(value)),
    ]),
    parse(body),
  ].join('\n')
}

function parse(markdown: string): string {
  return text(
    fromMarkdown(markdown, {
      extensions: [gfm()],
      mdastExtensions: [gfmFromMarkdown()],
    }),
  )
}

function text(node: Nodes): string {
  switch (node.type) {
    case 'break':
      return '\n'
    case 'image':
      return `Show image: ${node.alt || node.url || 'image'}`
    case 'imageReference':
      return `Show image: ${node.alt || 'image'}`
  }
  if ('value' in node) return node.value
  if (!('children' in node)) return ''
  return (node.children as Nodes[])
    .map(text)
    .join(INLINE.has(node.type) ? '' : '\n')
}

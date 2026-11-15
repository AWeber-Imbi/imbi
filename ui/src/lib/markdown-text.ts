import type { Nodes } from 'mdast'
import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmFromMarkdown } from 'mdast-util-gfm'
import { gfm } from 'micromark-extension-gfm'

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
 * The text GFM Markdown shows once rendered: no syntax, no raw HTML, a
 * line per block, and a deferred image's button label.
 */
export function markdownText(markdown: string): string {
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
    case 'html':
      return ''
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

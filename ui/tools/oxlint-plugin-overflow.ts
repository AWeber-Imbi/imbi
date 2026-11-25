import type { Context, ESTree, Visitor } from '@oxlint/plugins'
import { definePlugin, defineRule } from '@oxlint/plugins'

// A class token, with any variant prefixes (`sm:`, `data-[x]:`) removed.
function baseClass(token: string): string {
  let depth = 0
  let start = 0
  for (let i = 0; i < token.length; i++) {
    const ch = token[i]
    if (ch === '[') depth++
    else if (ch === ']') depth--
    else if (ch === ':' && depth === 0) start = i + 1
  }
  return token.slice(start).replace(/^!/, '')
}

const MAX_HEIGHT_RE = /^max-h-/
const CLIPS_RE = /^overflow(-y)?-(hidden|clip)$/
const SCROLLS_RE = /^(overflow(-y)?-(auto|scroll)|line-clamp-)/

/**
 * True when a class string caps an element's height and hides what does
 * not fit, with nothing that scrolls it or clamps it on purpose. Content
 * past the cap is then unreachable.
 */
export function clipsWithoutScroll(classes: string): boolean {
  let capsHeight = false
  let clips = false
  for (const token of classes.split(/\s+/)) {
    if (!token) continue
    const cls = baseClass(token)
    if (SCROLLS_RE.test(cls)) return false
    if (MAX_HEIGHT_RE.test(cls)) capsHeight = true
    if (CLIPS_RE.test(cls)) clips = true
  }
  return capsHeight && clips
}

const noClippedMaxHeight = defineRule({
  create(context: Context): Visitor {
    function check(
      value: string,
      node: ESTree.StringLiteral | ESTree.TemplateElement,
    ): void {
      if (clipsWithoutScroll(value)) {
        context.report({ messageId: 'clipped', node })
      }
    }

    return {
      Literal(node: ESTree.StringLiteral) {
        if (typeof node.value !== 'string') return
        if (!node.value.includes('max-h-')) return
        check(node.value, node)
      },
      TemplateLiteral(node: ESTree.TemplateLiteral) {
        for (const quasi of node.quasis) {
          const raw = quasi.value.cooked ?? quasi.value.raw
          if (!raw || !raw.includes('max-h-')) continue
          check(raw, quasi)
        }
      },
    }
  },
  meta: {
    docs: {
      description:
        'Disallow capping an element height while hiding its overflow, which makes content past the cap unreachable',
    },
    messages: {
      clipped:
        'This element caps its height (max-h-*) and hides its overflow, so content past the cap cannot be reached. Use overflow-y-auto, or line-clamp-* for an intentional preview. If a child scrolls instead, disable this rule on the line and say which child.',
    },
    schema: [],
    type: 'problem',
  },
})

export default definePlugin({
  meta: { name: 'overflow' },
  rules: {
    'no-clipped-max-height': noClippedMaxHeight,
  },
})

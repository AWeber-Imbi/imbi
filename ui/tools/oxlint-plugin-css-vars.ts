import type { Context, ESTree, Visitor } from '@oxlint/plugins'
import { definePlugin, defineRule } from '@oxlint/plugins'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const CSS_PROP_DEF_RE = /^\s*(--[\w-]+)\s*:/
const VAR_REF_RE = /var\(\s*(--[\w-]+)/g
const SHORTHAND_REF_RE = /(?<=[\w-])\(\s*(--[\w-]+)\s*\)/g

const DEFAULT_CSS_FILE = 'src/index.css'
const DEFAULT_IGNORE_PREFIXES = ['--radix-', '--assistant-', '--tw-']

interface CachedState {
  ignorePrefixes: string[]
  knownProperties: Set<string>
}

interface CssVarsSettings {
  cssFile?: string
  ignorePrefixes?: string[]
}

interface VarRef {
  index: number
  name: string
}

export function findSuggestion(
  input: string,
  candidates: Set<string>,
): null | string {
  let best: null | string = null
  let bestDist = Infinity
  const maxDist = Math.max(3, Math.floor(input.length * 0.4))
  for (const c of candidates) {
    const dist = levenshtein(input, c)
    if (dist < bestDist && dist <= maxDist) {
      bestDist = dist
      best = c
    }
  }
  return best
}

export function levenshtein(a: string, b: string): number {
  const m = a.length
  const n = b.length
  const d: number[][] = Array.from({ length: m + 1 }, (_, i) => [i])
  for (let j = 1; j <= n; j++) d[0][j] = j
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      d[i][j] = Math.min(
        d[i - 1][j] + 1,
        d[i][j - 1] + 1,
        d[i - 1][j - 1] + cost,
      )
    }
  }
  return d[m][n]
}

export function parseCssCustomProperties(cssFilePath: string): Set<string> {
  const css = readFileSync(cssFilePath, 'utf8')
  const props = new Set<string>()
  for (const line of css.split('\n')) {
    const match = line.match(CSS_PROP_DEF_RE)
    if (match) props.add(match[1])
  }
  return props
}

let cachedState: CachedState | null = null

export function extractVarRefs(str: string): VarRef[] {
  const refs: VarRef[] = []
  let match: null | RegExpExecArray
  VAR_REF_RE.lastIndex = 0
  while ((match = VAR_REF_RE.exec(str)) !== null) {
    refs.push({ index: match.index, name: match[1] })
  }
  SHORTHAND_REF_RE.lastIndex = 0
  while ((match = SHORTHAND_REF_RE.exec(str)) !== null) {
    if (!str.slice(Math.max(0, match.index - 3), match.index).endsWith('var')) {
      refs.push({ index: match.index, name: match[1] })
    }
  }
  return refs
}

function getState(context: Context): CachedState | null {
  if (cachedState) return cachedState

  let settings: CssVarsSettings | undefined
  try {
    settings = (context.settings as Record<string, unknown>)?.cssVars as
      | CssVarsSettings
      | undefined
  } catch {
    return null
  }

  const cssFile = settings?.cssFile ?? DEFAULT_CSS_FILE
  const cssFilePath = resolve(process.cwd(), cssFile)
  const ignorePrefixes = settings?.ignorePrefixes ?? DEFAULT_IGNORE_PREFIXES

  let knownProperties: Set<string>
  try {
    knownProperties = parseCssCustomProperties(cssFilePath)
  } catch {
    return null
  }

  cachedState = { ignorePrefixes, knownProperties }
  return cachedState
}

const noUnknownCssVar = defineRule({
  create(context: Context): Visitor {
    function checkString(
      value: string,
      node: ESTree.StringLiteral | ESTree.TemplateElement,
    ): void {
      const state = getState(context)
      if (!state) return

      const refs = extractVarRefs(value)
      for (const ref of refs) {
        if (state.ignorePrefixes.some((p) => ref.name.startsWith(p))) continue
        if (state.knownProperties.has(ref.name)) continue

        const suggestion = findSuggestion(ref.name, state.knownProperties)
        context.report({
          data: { name: ref.name, suggestion: suggestion || '' },
          messageId: suggestion ? 'unknownVarSuggestion' : 'unknownVar',
          node,
        })
      }
    }

    return {
      Literal(node: ESTree.StringLiteral) {
        if (typeof node.value !== 'string') return
        if (!node.value.includes('--')) return
        checkString(node.value, node)
      },
      TemplateLiteral(node: ESTree.TemplateLiteral) {
        for (const quasi of node.quasis) {
          const raw = quasi.value.cooked ?? quasi.value.raw
          if (!raw || !raw.includes('--')) continue
          checkString(raw, quasi)
        }
      },
    }
  },
  meta: {
    docs: {
      description: 'Disallow references to undefined CSS custom properties',
    },
    messages: {
      unknownVar: 'Unknown CSS custom property "{{name}}".',
      unknownVarSuggestion:
        'Unknown CSS custom property "{{name}}". Did you mean "{{suggestion}}"?',
    },
    schema: [],
    type: 'problem',
  },
})

export default definePlugin({
  meta: { name: 'css-vars' },
  rules: {
    'no-unknown-css-var': noUnknownCssVar,
  },
})

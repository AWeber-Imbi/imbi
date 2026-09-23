// Rewrite the `@/` path alias in emitted .d.ts files to relative paths (the
// converter's type reader has no path mapping), then write types/index.d.ts.
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'

const [root, ...modules] = process.argv.slice(2)

function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    return statSync(p).isDirectory() ? walk(p) : p.endsWith('.d.ts') ? [p] : []
  })
}

for (const file of walk(root)) {
  const text = readFileSync(file, 'utf8')
  const fixed = text.replace(/(['"])@\/([^'"]+)\1/g, (_, q, target) => {
    let rel = relative(dirname(file), join(root, target))
    if (!rel.startsWith('.')) rel = `./${rel}`
    return `${q}${rel}${q}`
  })
  if (fixed !== text) writeFileSync(file, fixed)
}

const lines = modules.map((m) => `export * from './${m}';`)
lines.push(
  "export * from './hooks/useEditableKeyValueMap';",
  "import type { ReactNode } from 'react';",
  '/** Wraps an Imbi UI tree with the providers the app root supplies. */',
  'export declare function ImbiProvider({ children }: { children: ReactNode }): import("react/jsx-runtime").JSX.Element;',
)
writeFileSync(join(root, 'index.d.ts'), lines.join('\n') + '\n')

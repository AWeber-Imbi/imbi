import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'
import { createImgComponent } from '@/lib/icon-sets/utils'

const deviconGlob = import.meta.glob<string>(
  '/node_modules/devicon/icons/**/*.svg',
  { eager: true, import: 'default', query: '?url' },
)

// Build lookup: "devicon-javascript-original" → url
const deviconIndex: Record<string, string> = {}
for (const [path, url] of Object.entries(deviconGlob)) {
  const filename = path.split('/').pop()!
  const name = filename.replace('.svg', '') // e.g. "javascript-original"
  deviconIndex[`devicon-${name}`] = url
}

export const DEVICON_ICONS: IconEntry[] = Object.entries(deviconIndex)
  .map(([value]) => ({
    label: value.slice(8).replace(/-/g, ' '), // strip "devicon-" → "javascript original"
    value,
  }))
  .sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('devicon-')) return null
  const url = deviconIndex[value]
  return url ? createImgComponent(url) : null
}

function resolveUrl(value: string): string | null {
  if (!value.startsWith('devicon-')) return null
  return deviconIndex[value] ?? null
}

iconRegistry.register({
  id: 'devicon',
  label: 'Devicon',
  description:
    'Technology and programming language icons, multiple style variants',
  valueFormat: 'devicon-{tech}-{variant}',
  icons: DEVICON_ICONS,
  resolve,
  resolveUrl,
})

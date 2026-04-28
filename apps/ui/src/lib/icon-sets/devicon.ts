import { createElement } from 'react'

import type {
  IconComponent,
  IconEntry,
  IconSetDefinition,
} from '@/lib/icon-registry'

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

// For the picker: one monochrome icon per tech, preferring -plain over -line.
// Collect which techs have plain/line variants, then pick one per tech.
const techVariants: Record<string, { line?: string; plain?: string }> = {}
for (const key of Object.keys(deviconIndex)) {
  if (key.endsWith('-plain')) {
    const tech = key.slice(8, -6) // strip "devicon-" and "-plain"
    if (!techVariants[tech]) techVariants[tech] = {}
    techVariants[tech].plain = key
  } else if (key.endsWith('-line')) {
    const tech = key.slice(8, -5) // strip "devicon-" and "-line"
    if (!techVariants[tech]) techVariants[tech] = {}
    techVariants[tech].line = key
  }
}

export const DEVICON_ICONS: IconEntry[] = Object.entries(techVariants)
  .map(([, variants]) => {
    const value = variants.line ?? variants.plain!
    const tech = value.slice(8).replace(/-plain$|-line$/, '') // strip prefix+variant
    return { label: tech.replace(/-/g, ' '), value }
  })
  .sort((a, b) => a.label.localeCompare(b.label))

function createGrayscaleImg(url: string): IconComponent {
  const Img: IconComponent = (props) => {
    const { className, height, width, ...rest } = props as Record<
      string,
      unknown
    >
    return createElement('img', {
      alt: '',
      className,
      height: height ?? 16,
      src: url,
      style: { filter: 'brightness(0)' },
      width: width ?? 16,
      ...rest,
    })
  }
  return Img
}

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('devicon-')) return null
  const url = deviconIndex[value]
  if (!url) return null
  return createGrayscaleImg(url)
}

function resolveUrl(value: string): null | string {
  if (!value.startsWith('devicon-')) return null
  return deviconIndex[value] ?? null
}

export const iconSet: IconSetDefinition = {
  description:
    'Technology and programming language icons, multiple style variants',
  icons: DEVICON_ICONS,
  id: 'devicon',
  label: 'Devicon',
  resolve,
  resolveUrl,
  valueFormat: 'devicon-{tech}-{variant}',
}

import { createElement } from 'react'

import { icons as lucideIcons } from 'lucide-react'
import { renderToStaticMarkup } from 'react-dom/server'

import type {
  IconComponent,
  IconEntry,
  IconSetDefinition,
} from '@/lib/icon-registry'
import { encodeSvgToDataUrl, toPascalCase } from '@/lib/icon-sets/utils'

export const LUCIDE_ICONS: IconEntry[] = Object.keys(lucideIcons)
  .filter((k) => k !== 'default' && k !== 'icons' && k !== 'createLucideIcon')
  .map((k) => ({
    label: k,
    value: `lucide-${k.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()}`,
  }))
  .sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('lucide-')) return null
  const name = toPascalCase(value.slice(7)) as keyof typeof lucideIcons
  return (lucideIcons[name] as IconComponent) || null
}

function resolveUrl(value: string, color?: string): null | string {
  const Component = resolve(value)
  if (!Component) return null
  try {
    const markup = renderToStaticMarkup(
      createElement(Component, {
        height: 128,
        width: 128,
        ...(color ? { color } : {}),
      }),
    )
    return encodeSvgToDataUrl(markup)
  } catch {
    return null
  }
}

export const iconSet: IconSetDefinition = {
  description: 'General purpose outline icons for UI elements',
  icons: LUCIDE_ICONS,
  id: 'lucide',
  label: 'Lucide',
  resolve,
  resolveUrl,
  valueFormat: 'lucide-{name}',
}

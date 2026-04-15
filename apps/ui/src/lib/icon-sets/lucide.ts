import { icons as lucideIcons } from 'lucide-react'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'
import { toPascalCase, encodeSvgToDataUrl } from '@/lib/icon-sets/utils'

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

function resolveUrl(value: string, color?: string): string | null {
  const Component = resolve(value)
  if (!Component) return null
  try {
    const markup = renderToStaticMarkup(
      createElement(Component, {
        width: 128,
        height: 128,
        ...(color ? { color } : {}),
      }),
    )
    return encodeSvgToDataUrl(markup)
  } catch {
    return null
  }
}

iconRegistry.register({
  id: 'lucide',
  label: 'Lucide',
  description: 'General purpose outline icons for UI elements',
  valueFormat: 'lucide-{name}',
  icons: LUCIDE_ICONS,
  resolve,
  resolveUrl,
})

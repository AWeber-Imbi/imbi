import * as TablerIcons from '@tabler/icons-react'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'
import {
  toPascalCase,
  encodeSvgToDataUrl,
  isForwardRefComponent,
} from '@/lib/icon-sets/utils'

const tablerLookup = TablerIcons as Record<string, unknown>

// Tabler icon exports are named "Icon*" (e.g. IconHome, IconHomeFilled)
export const TABLER_ICONS: IconEntry[] = Object.keys(tablerLookup)
  .filter((k) => isForwardRefComponent(tablerLookup[k]) && k.startsWith('Icon'))
  .map((k) => {
    const stripped = k.slice(4) // "IconHome" → "Home", "IconHomeFilled" → "HomeFilled"
    const kebab = stripped.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()
    return { label: stripped, value: `tabler-${kebab}` }
  })
  .sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('tabler-')) return null
  const name = 'Icon' + toPascalCase(value.slice(7))
  const Component = tablerLookup[name]
  return isForwardRefComponent(Component) ? Component : null
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
  id: 'tabler',
  label: 'Tabler',
  description: 'Clean open source SVG icons (outline and filled variants)',
  valueFormat: 'tabler-{name}',
  icons: TABLER_ICONS,
  resolve,
  resolveUrl,
})

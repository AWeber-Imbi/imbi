import { createElement } from 'react'

import * as simpleIcons from '@icons-pack/react-simple-icons'
import { renderToStaticMarkup } from 'react-dom/server'

import type {
  IconComponent,
  IconEntry,
  IconSetDefinition,
} from '@/lib/icon-registry'
import { encodeSvgToDataUrl, toPascalCase } from '@/lib/icon-sets/utils'

const siLookup = simpleIcons as Record<string, unknown>

const SI_ICONS: IconEntry[] = Object.keys(siLookup)
  .filter((k) => k.startsWith('Si') && !k.endsWith('Hex') && k !== 'default')
  .map((k) => {
    const raw = k.slice(2)
    const kebab = raw.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()
    return { label: raw, value: `si-${kebab}` }
  })
  .sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('si-')) return null
  const name = 'Si' + toPascalCase(value.slice(3))
  const Component = siLookup[name]
  return Component != null ? (Component as IconComponent) : null
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
  description: 'Brand icons for popular services, frameworks, and tools',
  icons: SI_ICONS,
  id: 'simple-icons',
  label: 'Simple Icons',
  resolve,
  resolveUrl,
  valueFormat: 'si-{name}',
}

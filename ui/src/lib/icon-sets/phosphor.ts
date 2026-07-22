import { type ComponentType, createElement } from 'react'

import * as PhosphorIcons from '@phosphor-icons/react'
import { renderToStaticMarkup } from 'react-dom/server'

import type {
  IconComponent,
  IconEntry,
  IconSetDefinition,
} from '@/lib/icon-registry'
import {
  encodeSvgToDataUrl,
  isForwardRefComponent,
  toPascalCase,
} from '@/lib/icon-sets/utils'

const phosphorLookup = PhosphorIcons as Record<string, unknown>

// Deduplicate by component identity (some icons have both Base and BaseIcon export
// pointing to the same component; 18 icons exist only under the *Icon name)
const PHOSPHOR_ICONS: IconEntry[] = Object.keys(phosphorLookup)
  .filter((k) => isForwardRefComponent(phosphorLookup[k]) && /^[A-Z]/.test(k))
  .reduce<{ entries: IconEntry[]; seen: Set<unknown> }>(
    (acc, k) => {
      const comp = phosphorLookup[k]
      if (acc.seen.has(comp)) return acc
      acc.seen.add(comp)
      acc.entries.push({
        label: k,
        value: `phosphor-${k.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()}`,
      })
      return acc
    },
    { entries: [], seen: new Set() },
  )
  .entries.sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('phosphor-')) return null
  const name = toPascalCase(value.slice(9))
  const Component = phosphorLookup[name]
  return isForwardRefComponent(Component) ? Component : null
}

function resolveUrl(value: string, color?: string): null | string {
  const Component = resolve(value)
  if (!Component) return null
  try {
    const markup = renderToStaticMarkup(
      createElement(Component as ComponentType<Record<string, unknown>>, {
        height: 128,
        weight: 'regular',
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
  description:
    'Flexible icon family for interfaces and diagrams (regular weight)',
  icons: PHOSPHOR_ICONS,
  id: 'phosphor',
  label: 'Phosphor',
  resolve,
  resolveUrl,
  valueFormat: 'phosphor-{name}',
}

import { useSyncExternalStore } from 'react'

import { ExternalLink } from 'lucide-react'

import { apiUrl } from '@/api/client'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent } from '@/lib/icon-registry'
import { createImgComponent } from '@/lib/icon-sets/utils'

// ---------------------------------------------------------------------------
// Loader registration
//
// Each loader's `load()` uses a dynamic import so Vite emits a separate chunk
// per icon set. The heavy per-library deps (lucide-react, @phosphor-icons,
// @tabler/icons-react, @icons-pack/react-simple-icons, devicon SVGs, aws SVGs)
// are only downloaded when a consumer first asks for an icon from that set,
// or when the IconPicker opens that set's tab.
// ---------------------------------------------------------------------------

iconRegistry.registerLoader({
  load: () => import('@/lib/icon-sets/lucide').then((m) => m.iconSet),
  matches: (v) => v.startsWith('lucide-'),
  meta: {
    description: 'General purpose outline icons for UI elements',
    id: 'lucide',
    label: 'Lucide',
    valueFormat: 'lucide-{name}',
  },
})

iconRegistry.registerLoader({
  load: () => import('@/lib/icon-sets/simple-icons').then((m) => m.iconSet),
  matches: (v) => v.startsWith('si-'),
  meta: {
    description: 'Brand icons for popular services, frameworks, and tools',
    id: 'simple-icons',
    label: 'Simple Icons',
    valueFormat: 'si-{name}',
  },
})

iconRegistry.registerLoader({
  load: () => import('@/lib/icon-sets/phosphor').then((m) => m.iconSet),
  matches: (v) => v.startsWith('phosphor-'),
  meta: {
    description:
      'Flexible icon family for interfaces and diagrams (regular weight)',
    id: 'phosphor',
    label: 'Phosphor',
    valueFormat: 'phosphor-{name}',
  },
})

iconRegistry.registerLoader({
  load: () => import('@/lib/icon-sets/tabler').then((m) => m.iconSet),
  matches: (v) => v.startsWith('tabler-'),
  meta: {
    description: 'Clean open source SVG icons (outline and filled variants)',
    id: 'tabler',
    label: 'Tabler',
    valueFormat: 'tabler-{name}',
  },
})

iconRegistry.registerLoader({
  load: () => import('@/lib/icon-sets/devicon').then((m) => m.iconSet),
  matches: (v) => v.startsWith('devicon-'),
  meta: {
    description:
      'Technology and programming language icons, multiple style variants',
    id: 'devicon',
    label: 'Devicon',
    valueFormat: 'devicon-{tech}-{variant}',
  },
})

// AWS values have no prefix, so this matcher is the fallback for any value
// that doesn't belong to a prefixed set. Registered last so prefixed loaders
// claim matching values first.
iconRegistry.registerLoader({
  load: () => import('@/lib/icon-sets/aws').then((m) => m.iconSet),
  matches: (v) =>
    !v.startsWith('lucide-') &&
    !v.startsWith('si-') &&
    !v.startsWith('phosphor-') &&
    !v.startsWith('tabler-') &&
    !v.startsWith('devicon-'),
  meta: {
    description: 'Amazon Web Services architecture and resource icons',
    id: 'aws',
    label: 'AWS',
    valueFormat: '{service-name}',
  },
})

// Re-exports
export { iconRegistry } from '@/lib/icon-registry'
export type { IconComponent } from '@/lib/icon-registry'

const MAX_ICON_CACHE_SIZE = 500
const iconUrlCache = new Map<string, null | string>()

const KNOWN_PREFIXES = [
  'lucide-',
  'si-',
  'phosphor-',
  'tabler-',
  'devicon-',
] as const

export function getIcon(
  iconName: null | string | undefined,
  fallback: null,
): IconComponent | null
// ---------------------------------------------------------------------------
// Synchronous resolution
//
// `getIcon` / `getIconUrl` stay synchronous so existing call sites keep
// working. If the owning set isn't loaded yet, they kick off a dynamic import
// (fire-and-forget) and return a fallback / null for now. Components that
// need to re-render when the set arrives should use the hooks below.
// ---------------------------------------------------------------------------
export function getIcon(
  iconName: null | string | undefined,
  fallback?: IconComponent,
): IconComponent
export function getIcon(
  iconName: null | string | undefined,
  fallback?: IconComponent | null,
): IconComponent | null {
  const fb = fallback === undefined ? (ExternalLink as IconComponent) : fallback

  if (!iconName) return fb

  // Uploaded files or absolute URLs → render as <img>
  if (iconName.startsWith('/uploads/')) {
    return createImgComponent(apiUrl(iconName))
  }
  if (iconName.startsWith('http://') || iconName.startsWith('https://')) {
    return createImgComponent(iconName)
  }

  const resolved = iconRegistry.resolve(iconName)
  if (resolved) return resolved

  // Legacy bare Lucide names (e.g. "external-link") — only works after
  // the lucide set has loaded.
  if (iconRegistry.isLoaded('lucide')) {
    const withPrefix = iconRegistry.resolve(`lucide-${iconName}`)
    if (withPrefix) return withPrefix
  }

  // Not loaded yet: trigger a load for the owning set. For unprefixed names
  // also load lucide so the legacy bare-name fallback can resolve (AWS names
  // are unprefixed too, so loadSetFor covers that side). Callers using
  // useIcon() will re-render once the set lands.
  void iconRegistry.loadSetFor(iconName)
  if (!hasKnownPrefix(iconName) && !iconRegistry.isLoaded('lucide')) {
    void iconRegistry.loadSet('lucide')
  }
  return fb
}
export function getIconUrl(
  iconName: null | string | undefined,
  color?: string,
): null | string {
  if (!iconName) return null
  const cacheKey = color ? `${iconName}@${color}` : iconName
  const cached = iconUrlCache.get(cacheKey)
  if (cached !== undefined) return cached
  const result = computeIconUrl(iconName, color)
  if (result === null) {
    // Don't cache nulls while sets may still be loading; let the next call
    // retry after the set arrives.
    void iconRegistry.loadSetFor(iconName)
    return null
  }
  if (iconUrlCache.size >= MAX_ICON_CACHE_SIZE) {
    iconUrlCache.delete(iconUrlCache.keys().next().value!)
  }
  iconUrlCache.set(cacheKey, result)
  return result
}

export function useIcon(
  iconName: null | string | undefined,
  fallback: null,
): IconComponent | null
export function useIcon(
  iconName: null | string | undefined,
  fallback?: IconComponent,
): IconComponent
// ---------------------------------------------------------------------------
// React hooks
// ---------------------------------------------------------------------------
export function useIcon(
  iconName: null | string | undefined,
  fallback?: IconComponent | null,
): IconComponent | null {
  useIconRegistryVersion()
  if (fallback === null) return getIcon(iconName, null)
  if (fallback === undefined) return getIcon(iconName)
  return getIcon(iconName, fallback)
}

/**
 * Subscribes to registry changes so the calling component re-renders when a
 * new icon set finishes loading. Include the returned value in useMemo deps
 * if you derive icons inside a memoized computation.
 */
export function useIconRegistryVersion(): number {
  return useSyncExternalStore(subscribe, getVersion, getVersion)
}

function computeIconUrl(iconName: string, color?: string): null | string {
  if (iconName.startsWith('/uploads/')) {
    return apiUrl(iconName)
  }
  if (iconName.startsWith('http://') || iconName.startsWith('https://')) {
    return iconName
  }
  return iconRegistry.resolveUrl(iconName, color)
}
function getVersion(): number {
  return iconRegistry.getVersion()
}
function hasKnownPrefix(value: string): boolean {
  for (const p of KNOWN_PREFIXES) if (value.startsWith(p)) return true
  return false
}

function subscribe(listener: () => void): () => void {
  return iconRegistry.subscribe(listener)
}

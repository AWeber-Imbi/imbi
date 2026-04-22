import { useSyncExternalStore } from 'react'
import { ExternalLink } from 'lucide-react'
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
  meta: {
    id: 'lucide',
    label: 'Lucide',
    description: 'General purpose outline icons for UI elements',
    valueFormat: 'lucide-{name}',
  },
  matches: (v) => v.startsWith('lucide-'),
  load: () => import('@/lib/icon-sets/lucide').then((m) => m.iconSet),
})

iconRegistry.registerLoader({
  meta: {
    id: 'simple-icons',
    label: 'Simple Icons',
    description: 'Brand icons for popular services, frameworks, and tools',
    valueFormat: 'si-{name}',
  },
  matches: (v) => v.startsWith('si-'),
  load: () => import('@/lib/icon-sets/simple-icons').then((m) => m.iconSet),
})

iconRegistry.registerLoader({
  meta: {
    id: 'phosphor',
    label: 'Phosphor',
    description:
      'Flexible icon family for interfaces and diagrams (regular weight)',
    valueFormat: 'phosphor-{name}',
  },
  matches: (v) => v.startsWith('phosphor-'),
  load: () => import('@/lib/icon-sets/phosphor').then((m) => m.iconSet),
})

iconRegistry.registerLoader({
  meta: {
    id: 'tabler',
    label: 'Tabler',
    description: 'Clean open source SVG icons (outline and filled variants)',
    valueFormat: 'tabler-{name}',
  },
  matches: (v) => v.startsWith('tabler-'),
  load: () => import('@/lib/icon-sets/tabler').then((m) => m.iconSet),
})

iconRegistry.registerLoader({
  meta: {
    id: 'devicon',
    label: 'Devicon',
    description:
      'Technology and programming language icons, multiple style variants',
    valueFormat: 'devicon-{tech}-{variant}',
  },
  matches: (v) => v.startsWith('devicon-'),
  load: () => import('@/lib/icon-sets/devicon').then((m) => m.iconSet),
})

// AWS values have no prefix, so this matcher is the fallback for any value
// that doesn't belong to a prefixed set. Registered last so prefixed loaders
// claim matching values first.
iconRegistry.registerLoader({
  meta: {
    id: 'aws',
    label: 'AWS',
    description: 'Amazon Web Services architecture and resource icons',
    valueFormat: '{service-name}',
  },
  matches: (v) =>
    !v.startsWith('lucide-') &&
    !v.startsWith('si-') &&
    !v.startsWith('phosphor-') &&
    !v.startsWith('tabler-') &&
    !v.startsWith('devicon-'),
  load: () => import('@/lib/icon-sets/aws').then((m) => m.iconSet),
})

// Re-exports
export { iconRegistry } from '@/lib/icon-registry'
export type { IconComponent } from '@/lib/icon-registry'

const MAX_ICON_CACHE_SIZE = 500
const iconUrlCache = new Map<string, string | null>()

const KNOWN_PREFIXES = [
  'lucide-',
  'si-',
  'phosphor-',
  'tabler-',
  'devicon-',
] as const

function hasKnownPrefix(value: string): boolean {
  for (const p of KNOWN_PREFIXES) if (value.startsWith(p)) return true
  return false
}

// ---------------------------------------------------------------------------
// Synchronous resolution
//
// `getIcon` / `getIconUrl` stay synchronous so existing call sites keep
// working. If the owning set isn't loaded yet, they kick off a dynamic import
// (fire-and-forget) and return a fallback / null for now. Components that
// need to re-render when the set arrives should use the hooks below.
// ---------------------------------------------------------------------------

export function getIcon(
  iconName: string | null | undefined,
  fallback: null,
): IconComponent | null
export function getIcon(
  iconName: string | null | undefined,
  fallback?: IconComponent,
): IconComponent
export function getIcon(
  iconName: string | null | undefined,
  fallback?: IconComponent | null,
): IconComponent | null {
  const fb = fallback === undefined ? (ExternalLink as IconComponent) : fallback

  if (!iconName) return fb

  // Uploaded files or absolute URLs → render as <img>
  if (
    iconName.startsWith('/uploads/') ||
    iconName.startsWith('http://') ||
    iconName.startsWith('https://')
  ) {
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
  iconName: string | null | undefined,
  color?: string,
): string | null {
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

function computeIconUrl(iconName: string, color?: string): string | null {
  if (iconName.startsWith('/uploads/')) {
    const baseUrl = import.meta.env.VITE_API_URL || '/api'
    return `${baseUrl}${iconName}`
  }
  if (iconName.startsWith('http://') || iconName.startsWith('https://')) {
    return iconName
  }
  return iconRegistry.resolveUrl(iconName, color)
}

// ---------------------------------------------------------------------------
// React hooks
// ---------------------------------------------------------------------------

function subscribe(listener: () => void): () => void {
  return iconRegistry.subscribe(listener)
}

function getVersion(): number {
  return iconRegistry.getVersion()
}

/**
 * Subscribes to registry changes so the calling component re-renders when a
 * new icon set finishes loading. Include the returned value in useMemo deps
 * if you derive icons inside a memoized computation.
 */
export function useIconRegistryVersion(): number {
  return useSyncExternalStore(subscribe, getVersion, getVersion)
}

export function useIcon(
  iconName: string | null | undefined,
  fallback: null,
): IconComponent | null
export function useIcon(
  iconName: string | null | undefined,
  fallback?: IconComponent,
): IconComponent
export function useIcon(
  iconName: string | null | undefined,
  fallback?: IconComponent | null,
): IconComponent | null {
  useIconRegistryVersion()
  if (fallback === null) return getIcon(iconName, null)
  if (fallback === undefined) return getIcon(iconName)
  return getIcon(iconName, fallback)
}

export function useIconUrl(
  iconName: string | null | undefined,
  color?: string,
): string | null {
  useIconRegistryVersion()
  return getIconUrl(iconName, color)
}

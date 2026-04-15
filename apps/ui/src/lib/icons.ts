import { ExternalLink } from 'lucide-react'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent } from '@/lib/icon-registry'
import { createImgComponent } from '@/lib/icon-sets/utils'

// Side-effect imports — each file self-registers with iconRegistry
import '@/lib/icon-sets/lucide'
import '@/lib/icon-sets/simple-icons'
import '@/lib/icon-sets/aws'
import '@/lib/icon-sets/devicon'
import '@/lib/icon-sets/phosphor'
import '@/lib/icon-sets/tabler'

// Re-exports for consumers
export { iconRegistry } from '@/lib/icon-registry'
export type { IconComponent } from '@/lib/icon-registry'
export { AWS_ICONS } from '@/lib/icon-sets/aws'

const MAX_ICON_CACHE_SIZE = 500
const iconUrlCache = new Map<string, string | null>()

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Resolve an icon name to a React component.
 *
 * Dispatches through the registry. Falls back to attempting a bare Lucide
 * name (no prefix) for backwards compatibility with legacy stored values.
 */
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

  // Try registry (handles lucide-, si-, aws, devicon-, phosphor-, tabler-)
  const resolved = iconRegistry.resolve(iconName)
  if (resolved) return resolved

  // Backward compat: bare Lucide name stored without prefix (e.g. "external-link")
  const withPrefix = iconRegistry.resolve(`lucide-${iconName}`)
  if (withPrefix) return withPrefix

  return fb
}

/**
 * Resolve an icon name to a URL for use in reagraph GraphNode.icon.
 */
export function getIconUrl(
  iconName: string | null | undefined,
  color?: string,
): string | null {
  if (!iconName) return null
  const cacheKey = color ? `${iconName}@${color}` : iconName
  const cached = iconUrlCache.get(cacheKey)
  if (cached !== undefined) return cached
  const result = computeIconUrl(iconName, color)
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

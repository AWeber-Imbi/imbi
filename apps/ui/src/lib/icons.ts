import { ExternalLink, icons as lucideIcons } from 'lucide-react'
import * as simpleIcons from '@icons-pack/react-simple-icons'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ComponentType, SVGProps } from 'react'

type IconComponent = ComponentType<
  SVGProps<SVGSVGElement> & { size?: number | string }
>

function toPascalCase(str: string): string {
  return str
    .split('-')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join('')
}

// ---------------------------------------------------------------------------
// AWS SVG icon index (built at compile time via Vite import.meta.glob)
// We import 64px Architecture-Service icons and 48px Light Resource icons.
// ---------------------------------------------------------------------------
const awsArchGlob = import.meta.glob<string>(
  '/node_modules/aws-svg-icons/lib/Architecture-Service-Icons_07302021/*/64/*.svg',
  { eager: true, import: 'default', query: '?url' },
)
const awsResGlob = import.meta.glob<string>(
  '/node_modules/aws-svg-icons/lib/Resource-Icons_07302021/*/Res_48_Light/*.svg',
  { eager: true, import: 'default', query: '?url' },
)

interface AwsEntry {
  url: string
  label: string
}

/**
 * Build a lookup map from normalized name → { url, label }.
 *
 * Architecture icons:  Arch_AWS-Lambda_64.svg → key "aws-lambda", label "AWS Lambda"
 * Resource icons:      Res_AWS-Systems-Manager_Parameter-Store_48_Light.svg → key "aws-systems-manager-parameter-store"
 */
function buildAwsIndex(): Record<string, AwsEntry> {
  const index: Record<string, AwsEntry> = {}

  for (const [path, url] of Object.entries(awsArchGlob)) {
    const filename = path.split('/').pop()!
    const match = filename.match(/^Arch_(.+)_64\.svg$/)
    if (!match) continue
    const raw = match[1] // e.g. "AWS-Lambda"
    const name = raw.toLowerCase()
    const label = raw.replace(/-/g, ' ')
    index[name] = { url, label }
  }

  for (const [path, url] of Object.entries(awsResGlob)) {
    const filename = path.split('/').pop()!
    const match = filename.match(/^Res_(.+)_48_Light\.svg$/)
    if (!match) continue
    const raw = match[1] // e.g. "AWS-Systems-Manager_Parameter-Store"
    const name = raw.replace(/_/g, '-').toLowerCase()
    const label = raw.replace(/[_-]/g, ' ')
    index[name] = { url, label }
  }

  return index
}

const awsIndex = buildAwsIndex()

/** AWS icon entries for use in the icon picker. */
export const AWS_ICONS: { label: string; value: string }[] = Object.entries(
  awsIndex,
)
  .map(([key, entry]) => ({ label: entry.label, value: key }))
  .sort((a, b) => a.label.localeCompare(b.label))

/** Set of all AWS icon keys for fast membership checks. */
const awsIconNames = new Set(Object.keys(awsIndex))

function resolveAwsUrl(iconName: string): string | null {
  const key = iconName.toLowerCase()
  const direct = awsIndex[key]
  if (direct) return direct.url
  for (const [k, entry] of Object.entries(awsIndex)) {
    if (k.endsWith(key)) return entry.url
  }
  return null
}

const iconUrlCache = new Map<string, string | null>()

/** Create a React component that renders an <img> for a given URL. */
function createImgComponent(url: string): IconComponent {
  const ImgIcon: IconComponent = (props) => {
    const { className, width, height, ...rest } = props as Record<
      string,
      unknown
    >
    return createElement('img', {
      src: url,
      alt: '',
      className,
      width: width ?? 16,
      height: height ?? 16,
      ...rest,
    })
  }
  return ImgIcon
}

const siLookup = simpleIcons as Record<string, unknown>

/**
 * Resolve an icon name to a React component.
 *
 * Naming convention:
 *   - "si-github"                            → Simple Icons (SiGithub)
 *   - "aws-lambda"                           → AWS SVG icon (Arch_AWS-Lambda_64.svg)
 *   - "aws-systems-manager-parameter-store"  → AWS SVG icon (Res_..._Parameter-Store_48_Light.svg)
 *   - "external-link"                        → Lucide (ExternalLink)
 *
 * Returns the fallback icon when the name is missing or unresolved.
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
  if (fallback === undefined) fallback = ExternalLink as IconComponent
  if (!iconName) return fallback

  // Simple Icons: si-github → SiGithub
  if (iconName.startsWith('si-')) {
    const name = 'Si' + toPascalCase(iconName.slice(3))
    const icon = siLookup[name]
    if (icon) return icon as IconComponent
    return fallback
  }

  // Lucide Icons: lucide-external-link → ExternalLink
  if (iconName.startsWith('lucide-')) {
    const name = toPascalCase(iconName.slice(7)) as keyof typeof lucideIcons
    return (lucideIcons[name] as IconComponent) || fallback
  }

  // AWS Icons: aws-lambda, amazon-s3, bottlerocket, etc.
  if (awsIconNames.has(iconName)) {
    const url = resolveAwsUrl(iconName)
    if (url) return createImgComponent(url)
    return fallback
  }

  // Uploaded files or absolute URLs → render as <img>
  if (
    iconName.startsWith('/uploads/') ||
    iconName.startsWith('http://') ||
    iconName.startsWith('https://')
  ) {
    return createImgComponent(iconName)
  }

  // Lucide: external-link → ExternalLink
  const name = toPascalCase(iconName) as keyof typeof lucideIcons
  return (lucideIcons[name] as IconComponent) || fallback
}

/**
 * Resolve an icon name to a URL suitable for reagraph's GraphNode.icon.
 *
 * Returns:
 *   - A direct URL for AWS icons (already stored as URL assets)
 *   - A data:image/svg+xml;base64 URL for Lucide / Simple Icons (rendered to SVG)
 *   - null when the icon name doesn't resolve
 *
 * Rendered icons use a fixed 32x32 viewBox and inherit currentColor, so the
 * caller can tint by setting the color on an enclosing element. Colors in
 * Simple Icons are baked in (they ship colored SVGs).
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
  iconUrlCache.set(cacheKey, result)
  return result
}

function computeIconUrl(iconName: string, color?: string): string | null {
  // Uploaded files: /uploads/{id} → resolve via API base URL
  if (iconName.startsWith('/uploads/')) {
    const baseUrl = import.meta.env.VITE_API_URL || '/api'
    return `${baseUrl}${iconName}`
  }

  // Absolute URLs: already a full image URL
  if (iconName.startsWith('http://') || iconName.startsWith('https://')) {
    return iconName
  }

  // AWS icons: direct URL from pre-built index
  if (awsIconNames.has(iconName)) {
    return resolveAwsUrl(iconName)
  }

  // Lucide / Simple Icons: render component → SVG markup → data URL
  const Component = getIcon(iconName, null)
  if (!Component) return null
  try {
    const markup = renderToStaticMarkup(
      createElement(Component, {
        width: 128,
        height: 128,
        ...(color ? { color } : {}),
      }),
    )
    const encoded =
      typeof btoa === 'function'
        ? btoa(unescape(encodeURIComponent(markup)))
        : Buffer.from(markup, 'utf-8').toString('base64')
    return `data:image/svg+xml;base64,${encoded}`
  } catch {
    return null
  }
}

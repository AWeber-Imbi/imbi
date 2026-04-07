import { ExternalLink, icons as lucideIcons } from 'lucide-react'
import * as simpleIcons from '@icons-pack/react-simple-icons'
import { createElement } from 'react'
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

/**
 * Build a lookup map from normalized name → SVG URL.
 *
 * Architecture icons:  Arch_AWS-Lambda_64.svg → "aws-lambda"
 * Resource icons:      Res_AWS-Systems-Manager_Parameter-Store_48_Light.svg → "aws-systems-manager-parameter-store"
 */
function buildAwsIndex(): Record<string, string> {
  const index: Record<string, string> = {}

  for (const [path, url] of Object.entries(awsArchGlob)) {
    // Extract filename: Arch_AWS-Lambda_64.svg → AWS-Lambda
    const filename = path.split('/').pop()!
    const match = filename.match(/^Arch_(.+)_64\.svg$/)
    if (!match) continue
    const name = match[1].toLowerCase()
    index[name] = url
  }

  for (const [path, url] of Object.entries(awsResGlob)) {
    // Extract filename: Res_AWS-Systems-Manager_Parameter-Store_48_Light.svg → AWS-Systems-Manager_Parameter-Store
    const filename = path.split('/').pop()!
    const match = filename.match(/^Res_(.+)_48_Light\.svg$/)
    if (!match) continue
    // Normalize underscores to hyphens for consistent lookup
    const name = match[1].replace(/_/g, '-').toLowerCase()
    index[name] = url
  }

  return index
}

const awsIndex = buildAwsIndex()

/** Create a React component that renders an <img> for an AWS SVG icon URL. */
function createAwsImgComponent(url: string): IconComponent {
  const AwsIcon: IconComponent = (props) => {
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
  return AwsIcon
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
  fallback: IconComponent = ExternalLink as IconComponent,
): IconComponent {
  if (!iconName) return fallback

  // Simple Icons: si-github → SiGithub
  if (iconName.startsWith('si-')) {
    const name = 'Si' + toPascalCase(iconName.slice(3))
    const icon = siLookup[name]
    if (icon) return icon as IconComponent
    return fallback
  }

  // AWS Icons: aws-lambda, aws-systems-manager-parameter-store
  if (iconName.startsWith('aws-')) {
    const key = iconName.toLowerCase()
    const url = awsIndex[key]
    if (url) return createAwsImgComponent(url)
    // Try partial match (suffix)
    for (const [k, u] of Object.entries(awsIndex)) {
      if (k.endsWith(key)) return createAwsImgComponent(u)
    }
    return fallback
  }

  // Lucide: external-link → ExternalLink
  const name = toPascalCase(iconName) as keyof typeof lucideIcons
  return (lucideIcons[name] as IconComponent) || fallback
}

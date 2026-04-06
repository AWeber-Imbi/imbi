import { ExternalLink, icons as lucideIcons } from 'lucide-react'
import * as simpleIcons from '@icons-pack/react-simple-icons'
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

/**
 * Resolve an icon name to a React component.
 *
 * Naming convention:
 *   - "si-github"      → Simple Icons (SiGithub)
 *   - "external-link"  → Lucide (ExternalLink)
 *
 * Returns the fallback icon when the name is missing or unresolved.
 */
export function getIcon(
  iconName: string | null | undefined,
  fallback: IconComponent = ExternalLink as IconComponent,
): IconComponent {
  if (!iconName) return fallback

  if (iconName.startsWith('si-')) {
    const name = 'Si' + toPascalCase(iconName.slice(3))
    const icon = (simpleIcons as Record<string, unknown>)[name]
    if (icon) return icon as IconComponent
    return fallback
  }

  const name = toPascalCase(iconName) as keyof typeof lucideIcons
  return (lucideIcons[name] as IconComponent) || fallback
}

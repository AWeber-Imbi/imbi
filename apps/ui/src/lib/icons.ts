import { ExternalLink, icons as lucideIcons } from 'lucide-react'
import * as simpleIcons from '@icons-pack/react-simple-icons'
import * as awsIcons from 'aws-react-icons'
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
 *   - "si-github"               → Simple Icons (SiGithub)
 *   - "aws-lambda"              → AWS Icons (ArchitectureServiceAWSLambda)
 *   - "aws:ArchitectureService" → AWS Icons by exact export name
 *   - "external-link"           → Lucide (ExternalLink)
 *
 * AWS icons use three prefixes in the library: ArchitectureService*,
 * ArchitectureGroup*, Category*, and Resource*. The shorthand "aws-"
 * prefix tries ArchitectureService{AWS,Amazon}{PascalName} first,
 * then falls back to a case-insensitive search. Use "aws:" for an
 * exact export name lookup.
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

  // AWS Icons exact: aws:ArchitectureServiceAWSLambda
  if (iconName.startsWith('aws:')) {
    const name = iconName.slice(4)
    const icon = awsLookup[name]
    if (icon) return icon as IconComponent
    return fallback
  }

  // AWS Icons shorthand: aws-lambda → try common prefixes
  if (iconName.startsWith('aws-')) {
    const pascal = toPascalCase(iconName.slice(4))
    const icon = resolveAwsIcon(pascal)
    if (icon) return icon
    return fallback
  }

  // Lucide: external-link → ExternalLink
  const name = toPascalCase(iconName) as keyof typeof lucideIcons
  return (lucideIcons[name] as IconComponent) || fallback
}

// Pre-built lookup tables for AWS icons
const awsLookup = awsIcons as Record<string, unknown>
const siLookup = simpleIcons as Record<string, unknown>

const AWS_PREFIXES = [
  'ArchitectureServiceAWS',
  'ArchitectureServiceAmazon',
  'ArchitectureService',
  'Category',
  'Resource',
  'ResourceAWS',
  'ResourceAmazon',
  'ArchitectureGroup',
]

function resolveAwsIcon(pascal: string): IconComponent | null {
  for (const prefix of AWS_PREFIXES) {
    const icon = awsLookup[prefix + pascal]
    if (icon) return icon as IconComponent
  }
  // Case-insensitive fallback
  const lower = pascal.toLowerCase()
  for (const key of Object.keys(awsLookup)) {
    if (key.toLowerCase().endsWith(lower)) {
      return awsLookup[key] as IconComponent
    }
  }
  return null
}

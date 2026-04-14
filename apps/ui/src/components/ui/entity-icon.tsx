import { getIcon } from '@/lib/icons'

interface EntityIconProps {
  icon: string
  className?: string
}

/**
 * Renders an icon from any supported source (Simple Icons, Lucide, AWS,
 * uploaded files, or absolute URLs). Use this instead of a raw <img> tag
 * when the icon value may be an identifier like "si-github" rather than a URL.
 */
export function EntityIcon({ icon, className }: EntityIconProps) {
  const Icon = getIcon(icon)
  return <Icon className={className} />
}

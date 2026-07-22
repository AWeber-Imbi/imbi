import { useIcon } from '@/lib/icons'

interface EntityIconProps {
  className?: string
  icon: string
}

/**
 * Renders an icon from any supported source (Simple Icons, Lucide, AWS,
 * uploaded files, or absolute URLs). Use this instead of a raw <img> tag
 * when the icon value may be an identifier like "si-github" rather than a URL.
 *
 * Uses `useIcon` so the component re-renders when the owning icon set
 * finishes its dynamic import.
 */
export function EntityIcon({ className, icon }: EntityIconProps) {
  const Icon = useIcon(icon)
  return <Icon className={className} />
}

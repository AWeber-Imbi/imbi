import { cn } from '@/lib/utils'
import { Gravatar } from './gravatar'

interface Props {
  email: string
  displayNames?: Map<string, string>
  size?: number
  className?: string
  textClassName?: string
  hideName?: boolean
  title?: string
}

/**
 * Compact user identity: Gravatar + display name (or local-part fallback).
 * Pass `displayNames` to resolve email → display_name.
 */
export function UserDisplay({
  email,
  displayNames,
  size = 18,
  className,
  textClassName,
  hideName = false,
  title,
}: Props) {
  const name = displayNames?.get(email) ?? email.split('@')[0] ?? email
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 truncate', className)}
      title={title ?? name}
    >
      <Gravatar
        email={email}
        size={size}
        className="flex-shrink-0 rounded-full"
      />
      {!hideName && (
        <span className={cn('truncate', textClassName)}>{name}</span>
      )}
    </span>
  )
}

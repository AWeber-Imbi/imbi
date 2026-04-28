import { cn } from '@/lib/utils'

import { Gravatar } from './gravatar'

interface Props {
  className?: string
  displayNames?: Map<string, string>
  email: string
  hideName?: boolean
  size?: number
  textClassName?: string
  title?: string
}

/**
 * Compact user identity: Gravatar + display name (or local-part fallback).
 * Pass `displayNames` to resolve email → display_name.
 */
export function UserDisplay({
  className,
  displayNames,
  email,
  hideName = false,
  size = 18,
  textClassName,
  title,
}: Props) {
  const name = displayNames?.get(email) ?? email.split('@')[0] ?? email
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 truncate', className)}
      title={title ?? name}
    >
      <Gravatar
        className="flex-shrink-0 rounded-full"
        email={email}
        size={size}
      />
      {!hideName && (
        <span className={cn('truncate', textClassName)}>{name}</span>
      )}
    </span>
  )
}

import { Link } from 'react-router-dom'

import { cn } from '@/lib/utils'

import { Gravatar } from './gravatar'

interface Props {
  className?: string
  displayNames?: Map<string, string>
  email: string
  hideName?: boolean
  /**
   * When true (default), wraps the chip in a link to /users/:email so the
   * user's profile page is reachable from any opslog/document/release row.
   */
  linkToProfile?: boolean
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
  linkToProfile = true,
  size = 18,
  textClassName,
  title,
}: Props) {
  const name = displayNames?.get(email) ?? email.split('@')[0] ?? email
  const body = (
    <>
      <Gravatar className="shrink-0 rounded-full" email={email} size={size} />
      {!hideName && (
        <span className={cn('truncate', textClassName)}>{name}</span>
      )}
    </>
  )
  if (linkToProfile && email) {
    return (
      <Link
        className={cn(
          'inline-flex items-center gap-1.5 truncate hover:underline',
          className,
        )}
        onClick={(event) => event.stopPropagation()}
        title={title ?? name}
        to={`/users/${encodeURIComponent(email)}`}
      >
        {body}
      </Link>
    )
  }
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 truncate', className)}
      title={title ?? name}
    >
      {body}
    </span>
  )
}

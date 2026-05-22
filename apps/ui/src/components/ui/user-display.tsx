import { Link } from 'react-router-dom'

import { cn } from '@/lib/utils'

import { Gravatar } from './gravatar'

interface Props {
  className?: string
  /** Override the resolved name (e.g. when the caller already has user.display_name in hand). */
  displayName?: string
  /** Email → display_name lookup, for row lists. Ignored if `displayName` is set. */
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
 * Resolution order for the rendered name:
 *   1. Explicit `displayName` prop
 *   2. `displayNames.get(email)` if a map is provided
 *   3. Local-part of the email (the bit before `@`)
 *   4. The email itself
 */
export function UserDisplay({
  className,
  displayName,
  displayNames,
  email,
  hideName = false,
  linkToProfile = true,
  size = 18,
  textClassName,
  title,
}: Props) {
  const name =
    displayName ?? displayNames?.get(email) ?? email.split('@')[0] ?? email
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

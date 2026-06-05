import { Bot } from 'lucide-react'

import { cn } from '@/lib/utils'

interface ActorBadgeProps {
  /** The actor login/name (e.g. a GitHub login like `kevin.vance`). */
  actor: string
}

// Service/automation actors get a bot icon instead of initials.
const BOT_PATTERN =
  /(\[bot\]|\bbot\b|-bot\b|github-actions|\bactions\b|automation|\bservice\b)/i

/**
 * Compact actor identity: a circular avatar + the actor name. People show
 * initials on an amber tint; bot/service actors (e.g. `github-actions`) show a
 * bot icon on a neutral tint. Used for the per-environment "Deployed by" value
 * where the actor is a remote login rather than an Imbi user (so it is not the
 * Gravatar-based `UserDisplay`).
 */
export function ActorBadge({ actor }: ActorBadgeProps) {
  const isBot = BOT_PATTERN.test(actor)
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <span
        className={cn(
          'flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
          isBot ? 'bg-tertiary text-secondary' : 'bg-amber-bg text-amber-text',
        )}
      >
        {isBot ? <Bot className="size-3.5" /> : initialsOf(actor)}
      </span>
      <span className="text-primary truncate text-sm">{actor}</span>
    </span>
  )
}

function initialsOf(actor: string): string {
  const parts = actor.split(/[^a-z0-9]+/i).filter(Boolean)
  const initials = parts
    .slice(0, 2)
    .map((p) => p[0])
    .join('')
  return (initials || actor.slice(0, 2)).toUpperCase()
}

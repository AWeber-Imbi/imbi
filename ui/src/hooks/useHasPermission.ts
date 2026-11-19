import { useAuth } from '@/hooks/useAuth'
import type { UserResponse } from '@/types'

/**
 * Return whether `user` holds `permission`. Admins hold every permission,
 * as the API's `require_permission` treats them.
 *
 * Without `orgSlug`, this checks the union of the user's roles in all their
 * organizations, as the global routes do. With `orgSlug`, it checks only
 * the user's role in that organization, as the org-scoped routes
 * (`/organizations/{org_slug}/...`) do. Those routes need membership even
 * for an admin, so a user who is not a member of `orgSlug` holds nothing
 * there.
 */
export function hasPermission(
  user: null | undefined | UserResponse,
  permission: string,
  orgSlug?: string,
): boolean {
  if (!user) return false
  if (orgSlug === undefined) {
    return !!user.is_admin || holds(user.permissions, permission)
  }
  const membership = (user.organizations ?? []).find(
    (m) => m.organization_slug === orgSlug,
  )
  if (!membership) return false
  // An API older than this UI omits `permissions` from each membership.
  return !!user.is_admin || holds(membership.permissions, permission)
}

/** {@link hasPermission} for the current user. */
export function useHasPermission(
  permission: string,
  orgSlug?: string,
): boolean {
  const { user } = useAuth()
  return hasPermission(user, permission, orgSlug)
}

/**
 * Return whether `held` has `permission`. Until release B (ADR 0028), a
 * `ticket:*` check also accepts the old `agent_task:*` name, because an
 * API older than release A gives only the old name.
 */
function holds(held: null | string[] | undefined, permission: string) {
  const names = held ?? []
  return (
    names.includes(permission) ||
    (permission.startsWith('ticket:') &&
      names.includes(permission.replace('ticket:', 'agent_task:')))
  )
}

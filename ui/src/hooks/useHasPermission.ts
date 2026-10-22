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
    return !!user.is_admin || (user.permissions ?? []).includes(permission)
  }
  const membership = (user.organizations ?? []).find(
    (m) => m.organization_slug === orgSlug,
  )
  if (!membership) return false
  return !!user.is_admin || membership.permissions.includes(permission)
}

/** {@link hasPermission} for the current user. */
export function useHasPermission(
  permission: string,
  orgSlug?: string,
): boolean {
  const { user } = useAuth()
  return hasPermission(user, permission, orgSlug)
}

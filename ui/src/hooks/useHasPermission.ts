import { useAuth } from '@/hooks/useAuth'

/**
 * Return whether the current user holds `permission`. Admins hold every
 * permission, as the API's `require_permission` treats them.
 */
export function useHasPermission(permission: string): boolean {
  const { user } = useAuth()
  return !!user?.is_admin || (user?.permissions ?? []).includes(permission)
}

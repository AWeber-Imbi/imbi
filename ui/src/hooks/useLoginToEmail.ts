import { useMemo } from 'react'

import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'

/**
 * Build a map from GitHub login to user email by matching email local-parts.
 * Returns both the display-name map (from useUserDisplayNames) and the login→email lookup.
 */
export function useLoginToEmail() {
  const { displayNames, users } = useUserDisplayNames()

  const loginToEmail = useMemo(() => {
    const m = new Map<string, string>()
    for (const u of users) {
      if (!u.email) continue
      const local = u.email.split('@')[0]
      if (local) m.set(local, u.email)
    }
    return m
  }, [users])

  return { displayNames, loginToEmail }
}

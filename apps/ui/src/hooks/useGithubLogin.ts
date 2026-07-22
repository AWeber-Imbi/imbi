import { useQuery } from '@tanstack/react-query'

import { getMyIdentities } from '@/api/endpoints'
import type { IdentityConnectionResponse } from '@/types'

// The GitHub package ships a single unified plugin (slug ``github``) in the
// v3 architecture — the per-flavor ``github-enterprise-cloud`` slug no longer
// exists, so an identity connection's ``plugin`` is always ``github``.
const GITHUB_PR_PLUGIN_SLUG = 'github'

// fallow-ignore-next-line complexity
export function useGithubLogin() {
  const {
    data: identities,
    isError,
    isLoading,
  } = useQuery({
    queryFn: ({ signal }) => getMyIdentities(signal),
    queryKey: ['me-identities'],
    // Match Dashboard's me-identities staleTime so the two consumers
    // share the cache instead of refetching independently on focus.
    staleTime: 5 * 60 * 1000,
  })

  const login = identities ? githubLoginFromIdentities(identities) : undefined
  const hasIdentity = !isLoading && !isError && !!login
  const notConnected = !isLoading && !isError && !login

  return { hasIdentity, isError, isLoading, login, notConnected }
}

// fallow-ignore-next-line complexity
function githubLoginFromIdentities(
  identities: IdentityConnectionResponse[],
): string | undefined {
  const conn = identities.find((i) => i.plugin === GITHUB_PR_PLUGIN_SLUG)
  if (!conn) return undefined
  const login = conn.metadata?.login
  return typeof login === 'string' && login ? login : undefined
}

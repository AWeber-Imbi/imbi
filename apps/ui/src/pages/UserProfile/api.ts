import { apiClient } from '@/api/client'

export type ActivityRecord = {
  environment_slug: null | string
  id: string
  link: null | string
  occurred_at: string
  project_id: null | string
  project_slug: null | string
  source: ActivitySource
  summary: string
  type: string
}

export type ActivityResponse = {
  data: ActivityRecord[]
}

export type ActivitySource =
  | 'conversation'
  | 'events'
  | 'note'
  | 'operations_log'
  | 'release'
  | 'upload'

export type ContributionBucket = {
  by_source: Record<string, number>
  count: number
  date: string
}

export type ContributionsResponse = {
  buckets: ContributionBucket[]
  since: string
  total: number
  tz: string
  until: string
}

export type DeploymentStats = {
  rolled_back: number
  success_rate: null | number
  total: number
}

export type IdentitiesResponse = {
  all: IdentityRecord[]
  primary: IdentityRecord | null
}

export type IdentityRecord = {
  display_name: null | string
  email: null | string
  last_used: null | string
  linked_at: null | string
  provider: string
  provider_user_id: string
}

export type StatsResponse = {
  deployments: DeploymentStats
  deployments_by_environment: Record<string, number>
  projects_touched: number
  since: string
  until: string
}

const encode = (email: string) => encodeURIComponent(email)

export const fetchContributions = (
  email: string,
  params?: { since?: string; tz?: string; until?: string },
  signal?: AbortSignal,
) =>
  apiClient.get<ContributionsResponse>(
    `/users/${encode(email)}/contributions`,
    params,
    signal,
  )

export const fetchStats = (
  email: string,
  params?: { since?: string; tz?: string; until?: string },
  signal?: AbortSignal,
) =>
  apiClient.get<StatsResponse>(`/users/${encode(email)}/stats`, params, signal)

export const fetchIdentities = (email: string, signal?: AbortSignal) =>
  apiClient.get<IdentitiesResponse>(
    `/users/${encode(email)}/identities`,
    undefined,
    signal,
  )

export const fetchActivity = (
  email: string,
  params?: { cursor?: string; limit?: number },
  signal?: AbortSignal,
): Promise<{ data: ActivityResponse; nextCursor: null | string }> =>
  apiClient
    .getWithHeaders<ActivityResponse>(
      `/users/${encode(email)}/activity`,
      params,
      signal,
    )
    .then(({ data, headers }) => ({
      data,
      nextCursor: parseNextCursor(headers.get('link')),
    }))

function parseNextCursor(link: null | string): null | string {
  if (!link) return null
  // Parse `Link: <url>; rel="next", <url>; rel="first"`
  const parts = link.split(',')
  for (const part of parts) {
    const match = /<([^>]+)>;\s*rel="next"/.exec(part.trim())
    if (match) {
      const url = match[1]
      const queryIndex = url.indexOf('?')
      if (queryIndex < 0) return null
      const search = new URLSearchParams(url.slice(queryIndex + 1))
      return search.get('cursor')
    }
  }
  return null
}

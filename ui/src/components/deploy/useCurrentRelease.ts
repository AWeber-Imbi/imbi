import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'

import { listCurrentReleases } from '@/api/endpoints'
import type { CurrentReleaseEnvironment, Environment } from '@/types'

interface UseCurrentReleaseOptions {
  env: Environment | undefined
  open: boolean
  orgSlug: string
  projectId: string
}

interface UseCurrentReleaseResult {
  current: CurrentReleaseEnvironment | undefined
  isError: boolean
  isLoading: boolean
}

export function useCurrentRelease({
  env,
  open,
  orgSlug,
  projectId,
}: UseCurrentReleaseOptions): UseCurrentReleaseResult {
  const {
    data: currentReleases = [],
    isError,
    isLoading,
  } = useQuery<CurrentReleaseEnvironment[]>({
    enabled: open && !!orgSlug && !!projectId,
    queryFn: ({ signal }) => listCurrentReleases(orgSlug, projectId, signal),
    queryKey: ['currentReleases', orgSlug, projectId],
  })

  const current = useMemo(
    () =>
      env
        ? currentReleases.find((r) => r.environment.slug === env.slug)
        : undefined,
    [currentReleases, env],
  )

  return { current, isError, isLoading }
}

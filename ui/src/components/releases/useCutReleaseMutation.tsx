import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { cutRelease } from '@/api/releases'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { CutReleaseRequest } from '@/types'

interface UseCutReleaseOptions {
  onSuccess?: () => void
  orgSlug: string
  projectId: string
}

interface UseCutReleaseResult {
  cut: (body: CutReleaseRequest) => void
  isPending: boolean
}

/**
 * Cut a tag + GitHub release for a library project. Unlike deploy/promote
 * there is no async workflow run to watch — the cut response is synchronous,
 * so we go straight to a success toast and invalidate the release queries.
 */
export function useCutReleaseMutation({
  onSuccess,
  orgSlug,
  projectId,
}: UseCutReleaseOptions): UseCutReleaseResult {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (body: CutReleaseRequest) =>
      cutRelease(orgSlug, projectId, body),
    onError: (err) => {
      toast.error(
        err instanceof ApiError
          ? (extractApiErrorDetail(err) ?? err.message)
          : (err as Error).message,
      )
    },
    onSuccess: (data) => {
      for (const key of [
        ['releaseDrift', orgSlug, projectId],
        ['releaseHistory', orgSlug, projectId],
        ['currentReleases', orgSlug, projectId],
        ['project-releases', orgSlug, projectId],
      ]) {
        void queryClient.invalidateQueries({ queryKey: key })
      }
      const url = data.release_url
      toast.success(
        `Released ${data.tag}`,
        url
          ? {
              action: {
                label: 'View release',
                onClick: () => window.open(url, '_blank', 'noopener'),
              },
            }
          : undefined,
      )
      if (data.warning) {
        toast.warning(`Release ${data.tag} recorded with a warning`, {
          description: data.warning,
          duration: 10_000,
        })
      }
      onSuccess?.()
    },
  })

  return {
    cut: (body: CutReleaseRequest) => mutation.mutate(body),
    isPending: mutation.isPending,
  }
}

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { cutRelease } from '@/api/releases'
import type { ReleaseBuildStarted } from '@/components/deploy/DeploymentModal'
import { handleDispatchedBuild } from '@/components/deploy/releaseBuildHandoff'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { CutReleaseRequest } from '@/types'

interface UseCutReleaseOptions {
  /**
   * Called when the cut dispatched a release build instead of creating
   * the tag inline, so the caller can mount a `ReleaseBuildWatcher`.
   */
  onBuildStarted?: (build: ReleaseBuildStarted) => void
  onSuccess?: () => void
  orgSlug: string
  projectId: string
}

interface UseCutReleaseResult {
  cut: (body: CutReleaseRequest) => void
  isPending: boolean
}

/**
 * Cut a tag + GitHub release for a library project.
 *
 * Synchronous only when the project has no Release workflow configured:
 * then the tag and release already exist by the time this returns and a
 * success toast is honest. With one configured the response comes back
 * `phase: 'building'` — the dispatched workflow is what creates them —
 * so the toast has to follow the build instead of declaring victory.
 */
export function useCutReleaseMutation({
  onBuildStarted,
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
      if (
        handleDispatchedBuild(data, {
          // A library release has no deploy target.
          envName: null,
          onBuildStarted,
          orgSlug,
          projectId,
          tagFallback: data.tag,
        })
      ) {
        onSuccess?.()
        return
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

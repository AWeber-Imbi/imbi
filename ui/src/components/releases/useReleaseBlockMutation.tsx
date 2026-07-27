import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { blockRelease, unblockRelease } from '@/api/releases'
import { extractApiErrorDetail } from '@/lib/apiError'

interface UseReleaseBlockOptions {
  orgSlug: string
  projectId: string
}

interface UseReleaseBlockResult {
  block: (tag: string, reason: string) => void
  isPending: boolean
  unblock: (tag: string) => void
}

const message = (err: unknown): string =>
  err instanceof ApiError
    ? (extractApiErrorDetail(err) ?? err.message)
    : (err as Error).message

/**
 * Block / unblock a release tag. Both write the same `blocked_*` state on
 * the release, so they share one invalidation set: the release history and
 * the deployment pipeline both render the block.
 */
export function useReleaseBlockMutation({
  orgSlug,
  projectId,
}: UseReleaseBlockOptions): UseReleaseBlockResult {
  const queryClient = useQueryClient()
  const invalidate = () => {
    for (const key of [
      ['releaseHistory', orgSlug, projectId],
      ['currentReleases', orgSlug, projectId],
      ['project-releases', orgSlug, projectId],
    ]) {
      void queryClient.invalidateQueries({ queryKey: key })
    }
  }

  const blockMutation = useMutation({
    mutationFn: ({ reason, tag }: { reason: string; tag: string }) =>
      blockRelease(orgSlug, projectId, tag, { reason }),
    onError: (err) => toast.error(message(err)),
    onSuccess: (data) => {
      invalidate()
      toast.success(`Blocked ${data.tag}`, {
        description: 'Deploys and promotes of this release are now refused.',
      })
    },
  })

  const unblockMutation = useMutation({
    mutationFn: (tag: string) => unblockRelease(orgSlug, projectId, tag),
    onError: (err) => toast.error(message(err)),
    onSuccess: (data) => {
      invalidate()
      toast.success(`Unblocked ${data.tag}`, {
        description: 'This release can be deployed again.',
      })
    },
  })

  return {
    block: (tag: string, reason: string) =>
      blockMutation.mutate({ reason, tag }),
    isPending: blockMutation.isPending || unblockMutation.isPending,
    unblock: (tag: string) => unblockMutation.mutate(tag),
  }
}

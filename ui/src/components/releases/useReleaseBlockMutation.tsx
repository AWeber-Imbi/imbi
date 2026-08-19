import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import {
  addReleaseBlocker,
  resolveReleaseBlocker,
  unblockRelease,
} from '@/api/releases'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { BlockerType } from '@/types'

interface AddBlockerArgs {
  description: string
  tag: string
  type: BlockerType
}

interface ResolveBlockerArgs {
  blockerId: string
  tag: string
}

interface UseReleaseBlockOptions {
  /**
   * Fires after the server confirms an unblock. The release-in-flight
   * banner keys off `promote-status`, which still reads `build_failed`
   * after the block record is cleared — the caller has to retire that
   * banner itself or it keeps claiming the tag is blocked.
   */
  onUnblocked?: () => void
  orgSlug: string
  projectId: string
}

interface UseReleaseBlockResult {
  block: (args: AddBlockerArgs) => void
  isPending: boolean
  resolve: (args: ResolveBlockerArgs) => void
  unblock: (tag: string) => void
}

const message = (err: unknown): string =>
  err instanceof ApiError
    ? (extractApiErrorDetail(err) ?? err.message)
    : (err as Error).message

/**
 * File, resolve, and clear the blockers on a release. All three change
 * whether the release can ship, so they share one invalidation set: the
 * release history and the deployment pipeline both render the block.
 */
export function useReleaseBlockMutation({
  onUnblocked,
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
    mutationFn: ({ description, tag, type }: AddBlockerArgs) =>
      addReleaseBlocker(orgSlug, projectId, tag, { description, type }),
    onError: (err) => toast.error(message(err)),
    onSuccess: () => {
      invalidate()
      toast.success('Blocker added', {
        description: 'Deploys and promotes of this release are now refused.',
      })
    },
  })

  const resolveMutation = useMutation({
    mutationFn: ({ blockerId, tag }: ResolveBlockerArgs) =>
      resolveReleaseBlocker(orgSlug, projectId, tag, blockerId),
    onError: (err) => toast.error(message(err)),
    onSuccess: () => {
      invalidate()
      toast.success('Blocker resolved')
    },
  })

  const unblockMutation = useMutation({
    mutationFn: (tag: string) => unblockRelease(orgSlug, projectId, tag),
    onError: (err) => toast.error(message(err)),
    onSuccess: (data) => {
      invalidate()
      onUnblocked?.()
      toast.success(`Unblocked ${data.tag}`, {
        description: 'This release can be deployed again.',
      })
    },
  })

  return {
    block: (args: AddBlockerArgs) => blockMutation.mutate(args),
    isPending:
      blockMutation.isPending ||
      resolveMutation.isPending ||
      unblockMutation.isPending,
    resolve: (args: ResolveBlockerArgs) => resolveMutation.mutate(args),
    unblock: (tag: string) => unblockMutation.mutate(tag),
  }
}

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { triggerDeployment } from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { CurrentReleaseEnvironment, Environment } from '@/types'

import type { DeploymentRunStarted } from './DeploymentModal'

interface SelectedVersion {
  label: null | string
  sha: string
}

interface UseDeployMutationOptions {
  current: CurrentReleaseEnvironment | undefined
  env: Environment | undefined
  envSlug: string
  isFirstEnv: boolean
  onClose: () => void
  onRunStarted?: (run: DeploymentRunStarted) => void
  orgSlug: string
  projectId: string
  selected: null | SelectedVersion
}

interface UseDeployMutationResult {
  isPending: boolean
  isRedeploy: boolean
  onDeploy: () => void
}

export function useDeployMutation({
  current,
  env,
  envSlug,
  isFirstEnv,
  onClose,
  onRunStarted,
  orgSlug,
  projectId,
  selected,
}: UseDeployMutationOptions): UseDeployMutationResult {
  const currentCommittish = current?.release?.committish ?? null
  const currentTag = current?.release?.tag ?? null
  const isRedeploy =
    !!current?.release &&
    !!selected &&
    (isFirstEnv
      ? !!currentCommittish &&
        (currentCommittish === selected.sha ||
          selected.sha.startsWith(currentCommittish) ||
          currentCommittish.startsWith(selected.sha))
      : currentTag === selected.label)

  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (payload: SelectedVersion) =>
      triggerDeployment(orgSlug, projectId, {
        action: isRedeploy ? 'redeploy' : 'deploy',
        committish: payload.sha,
        environment: envSlug,
        ref_label: payload.label,
      }),
    onError: (err) => {
      toast.error(
        err instanceof ApiError
          ? (extractApiErrorDetail(err) ?? err.message)
          : (err as Error).message,
      )
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({
        queryKey: ['currentReleases', orgSlug, projectId],
      })
      const url = data.run.run_url
      const envName = env?.name ?? envSlug
      if (onRunStarted && data.run.run_id) {
        const toastId = toast.loading(`Deploying to ${envName}…`, {
          action: url
            ? {
                label: 'View run',
                onClick: () => window.open(url, '_blank', 'noopener'),
              }
            : undefined,
          description: data.run.status
            ? `status: ${data.run.status}`
            : undefined,
          icon: <Loader2 className="size-4 animate-spin" />,
        })
        onRunStarted({
          actionLabel: url ? 'View run' : undefined,
          actionUrl: url,
          envName,
          initialStatus: data.run.status,
          originOrgSlug: orgSlug,
          originProjectId: projectId,
          runId: data.run.run_id,
          runUrl: url,
          toastId,
        })
      } else {
        toast.success(
          `Workflow dispatched to ${envName}`,
          url
            ? {
                action: {
                  label: 'View run',
                  onClick: () => window.open(url, '_blank', 'noopener'),
                },
              }
            : undefined,
        )
      }
      onClose()
    },
  })

  const onDeploy = () => {
    if (!selected) return
    mutation.mutate(selected)
  }

  return { isPending: mutation.isPending, isRedeploy, onDeploy }
}

// Dispatch mutations for the Deployments tab. Mirrors the toast + run
// watcher wiring of the deploy/promote modal hooks, decoupled from the
// modal lifecycle so inline cards can dispatch directly.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { promoteDeployment, triggerDeployment } from '@/api/endpoints'
import type { DeploymentRunStarted } from '@/components/deploy/DeploymentModal'
import { extractApiErrorDetail } from '@/lib/apiError'

export interface DeploymentActions {
  deploy: (req: DeployRequest) => void
  deployPending: boolean
  /** SHA of the deploy currently in flight (drives per-row spinners). */
  deployPendingSha: null | string
  promote: (req: PromoteRequest) => void
  promotePending: boolean
}

export interface DeployRequest {
  action: 'deploy' | 'redeploy'
  envName: string
  envSlug: string
  refLabel: null | string
  /** Changes the loading-toast verb; the request is still a deploy. */
  rollback?: boolean
  sha: string
}

export interface PromoteRequest {
  fromEnvironment: string
  notes: string
  sha: string
  tag: string
  toEnvironment: string
  toEnvName: string
}

interface UseDeploymentActionsOptions {
  onRunStarted?: (run: DeploymentRunStarted) => void
  orgSlug: string
  projectId: string
}

export function useDeploymentActions({
  onRunStarted,
  orgSlug,
  projectId,
}: UseDeploymentActionsOptions): DeploymentActions {
  const queryClient = useQueryClient()
  const invalidate = () => {
    for (const key of [
      'currentReleases',
      'promotionOptions',
      'releaseHistory',
    ]) {
      void queryClient.invalidateQueries({
        queryKey: [key, orgSlug, projectId],
      })
    }
  }
  const onError = (err: unknown) => {
    toast.error(
      err instanceof ApiError
        ? (extractApiErrorDetail(err) ?? err.message)
        : (err as Error).message,
    )
  }

  const deployMutation = useMutation({
    mutationFn: (req: DeployRequest) =>
      triggerDeployment(orgSlug, projectId, {
        action: req.action,
        committish: req.sha,
        environment: req.envSlug,
        ref_label: req.refLabel,
      }),
    onError,
    // fallow-ignore-next-line complexity
    onSuccess: (data, req) => {
      invalidate()
      const url = data.run.run_url
      const label = req.refLabel ?? req.sha.slice(0, 7)
      const verb = req.rollback ? 'Rolling back' : 'Deploying'
      if (onRunStarted && data.run.run_id) {
        const toastId = toast.loading(
          req.rollback
            ? `${verb} ${req.envName} to ${label}…`
            : `${verb} ${label} to ${req.envName}…`,
          {
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
          },
        )
        onRunStarted({
          actionLabel: url ? 'View run' : undefined,
          actionUrl: url,
          envName: req.envName,
          initialStatus: data.run.status,
          originOrgSlug: orgSlug,
          originProjectId: projectId,
          runId: data.run.run_id,
          runUrl: url,
          toastId,
        })
      } else {
        toast.success(
          `Workflow dispatched to ${req.envName}`,
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
    },
  })

  const promoteMutation = useMutation({
    mutationFn: (req: PromoteRequest) =>
      promoteDeployment(orgSlug, projectId, {
        action: 'promote',
        from_committish: req.sha,
        from_environment: req.fromEnvironment,
        prerelease: false,
        release_name: req.tag,
        release_notes_markdown: req.notes,
        tag: req.tag,
        to_environment: req.toEnvironment,
      }),
    onError,
    // fallow-ignore-next-line complexity
    onSuccess: (data, req) => {
      invalidate()
      const releaseUrl = data.release_url
      const runUrl = data.run.run_url
      const tagLabel = data.tag ?? req.tag
      // Prefer the run URL when present; fall back to the release URL so
      // the watcher's recreated toast still has a useful action.
      const actionUrl = runUrl ?? releaseUrl
      const actionLabel = runUrl
        ? 'View run'
        : releaseUrl
          ? 'View release'
          : undefined
      if (onRunStarted && data.run.run_id) {
        const toastId = toast.loading(
          `Promoting ${tagLabel} to ${req.toEnvName}…`,
          {
            action:
              actionUrl && actionLabel
                ? {
                    label: actionLabel,
                    onClick: () => window.open(actionUrl, '_blank', 'noopener'),
                  }
                : undefined,
            description: data.run.status
              ? `status: ${data.run.status}`
              : undefined,
            icon: <Loader2 className="size-4 animate-spin" />,
          },
        )
        onRunStarted({
          actionLabel,
          actionUrl,
          envName: req.toEnvName,
          initialStatus: data.run.status,
          originOrgSlug: orgSlug,
          originProjectId: projectId,
          runId: data.run.run_id,
          runUrl,
          toastId,
        })
      } else {
        const url = releaseUrl ?? runUrl
        toast.success(
          `Promoted ${tagLabel} to ${req.toEnvName}`,
          url
            ? {
                action: {
                  label: 'View',
                  onClick: () => window.open(url, '_blank', 'noopener'),
                },
              }
            : undefined,
        )
      }
      // Non-fatal partial success (e.g. the tag + release cut but the
      // GitHub Deployments POST failed) surfaces as an amber toast.
      if (data.warning) {
        toast.warning(`Promote to ${req.toEnvName} recorded with a warning`, {
          description: data.warning,
          duration: 10_000,
        })
      }
    },
  })

  return {
    deploy: (req) => deployMutation.mutate(req),
    deployPending: deployMutation.isPending,
    deployPendingSha: deployMutation.isPending
      ? (deployMutation.variables?.sha ?? null)
      : null,
    promote: (req) => promoteMutation.mutate(req),
    promotePending: promoteMutation.isPending,
  }
}

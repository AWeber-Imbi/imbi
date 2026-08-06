import { useEffect, useRef } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  Rocket,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'

import { getPromoteStatus, type PromoteStatus } from '@/api/endpoints'

/** States the watcher stops polling on. */
const TERMINAL_STATES: ReadonlySet<PromoteStatus['status']> = new Set([
  'build_failed',
  'failed',
  'success',
])

interface ReleaseBuildWatcherProps {
  /** Where the promote is heading; `null` for a release-only cut. */
  envName: null | string
  onTerminal: () => void
  orgSlug: string
  projectId: string
  /** Workflow run URL known at dispatch time. */
  runUrl?: null | string
  tag: string
  toastId: number | string
}

/**
 * Follows a dispatched promote via `/deployments/promote-status`.
 *
 * Covers the whole two-phase lifecycle — `building` while the release
 * workflow cuts the tag and builds the artifact, then `deploying` once
 * Imbi has created the Deployment — rather than handing off to
 * {@link DeploymentRunWatcher} partway. It has to: the Deployment is
 * created by the promote watcher on the server, so the browser never
 * learns its run id and has nothing to poll `/runs/{id}` with.
 * `promote-status` reports both phases, so one poll tells the whole
 * story.
 *
 * Polls more slowly than the deployment watcher on purpose: a release
 * build takes minutes, and can sit queued behind another release since
 * the workflow serializes per repository, so a 4s tick would be
 * thousands of wasted requests.
 *
 * Renders nothing — a side-effect component the parent mounts per
 * in-flight promote.
 */
export function ReleaseBuildWatcher(props: ReleaseBuildWatcherProps): null {
  const { envName, onTerminal, orgSlug, projectId, runUrl, tag, toastId } =
    props

  const settledRef = useRef(false)

  const query = useQuery<PromoteStatus>({
    enabled: !settledRef.current,
    queryFn: ({ signal }) => getPromoteStatus(orgSlug, projectId, signal),
    queryKey: ['promote-status', orgSlug, projectId],
    refetchInterval: (q) => {
      if (settledRef.current) return false
      const status = q.state.data?.status
      if (status && TERMINAL_STATES.has(status)) return false
      return 6000
    },
    refetchIntervalInBackground: false,
    retry: 3,
  })

  useEffect(() => {
    if (settledRef.current) return
    const data = query.data
    if (!data) return
    const url = data.artifact_run_url ?? runUrl
    const action = url
      ? {
          label: 'View build',
          onClick: () => window.open(url, '_blank', 'noopener'),
        }
      : undefined
    const target = envName ? ` to ${envName}` : ''

    if (data.status === 'building') {
      toast.loading(`Building release ${tag}…`, {
        action,
        description: 'The release workflow is cutting the tag and building.',
        icon: <Loader2 className="size-4 animate-spin" />,
        id: toastId,
      })
      return
    }
    if (data.status === 'deploying') {
      // The build is green: the tag and the remote Release now exist and
      // Imbi has created the Deployment. Keep polling — the rollout's
      // outcome arrives on this same status.
      toast.loading(`Deploying ${tag}${target}…`, {
        action,
        icon: <Loader2 className="size-4 animate-spin" />,
        id: toastId,
      })
      return
    }
    if (data.status === 'success') {
      settledRef.current = true
      toast.success(envName ? `Released ${tag}${target}` : `Released ${tag}`, {
        action,
        icon: <CheckCircle2 className="size-4 text-emerald-500" />,
        id: toastId,
      })
      onTerminal()
      return
    }
    if (data.status === 'build_failed') {
      settledRef.current = true
      toast.error(`Release build for ${tag} failed`, {
        action,
        description:
          data.error ??
          'The release is blocked. Fix the build and promote a new ' +
            'version, or unblock this one to retry it.',
        icon: <XCircle className="size-4 text-rose-500" />,
        id: toastId,
      })
      onTerminal()
      return
    }
    if (data.status === 'failed') {
      settledRef.current = true
      // Not a failed build: Imbi lost track of it, or could not finish
      // after it went green. The tag is deliberately left shippable.
      toast.message(`Lost track of the release build for ${tag}`, {
        action,
        description:
          data.error ??
          'Check the workflow run; the tag was not blocked, so it can ' +
            'still be deployed once green.',
        icon: <Rocket className="size-4" />,
        id: toastId,
      })
      onTerminal()
    }
    // `idle` — nothing recorded yet; keep polling.
  }, [query.data, envName, onTerminal, runUrl, tag, toastId])

  useEffect(() => {
    if (!query.isError || settledRef.current) return
    settledRef.current = true
    const url = runUrl
    toast.message(`Lost track of the release build for ${tag}`, {
      action: url
        ? {
            label: 'View build',
            onClick: () => window.open(url, '_blank', 'noopener'),
          }
        : undefined,
      description: 'Status polling failed; check the workflow run directly.',
      icon: <ExternalLink className="size-4" />,
      id: toastId,
    })
    onTerminal()
  }, [query.isError, onTerminal, runUrl, tag, toastId])

  return null
}

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
import { sanitizeHttpUrl } from '@/lib/utils'

/**
 * `toast`, minus the talking, for a run the page already banners.
 *
 * Swapped in for the real thing so silence cannot skip the settling:
 * every branch below still stops the poll and tells the parent, it just
 * says nothing while doing it. `DeploymentRunWatcher` shares it for its
 * banner-only (toast-less) runs.
 */
export const SILENT: Pick<
  typeof toast,
  'error' | 'loading' | 'message' | 'success'
> = {
  error: () => '',
  loading: () => '',
  message: () => '',
  success: () => '',
}

/** States the watcher stops polling on. */
const TERMINAL_STATES: ReadonlySet<PromoteStatus['status']> = new Set([
  'build_failed',
  'deploy_failed',
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
  /**
   * True when the page already carries a banner for this promote.
   *
   * The banner says everything the toasts say, stays put for as long as
   * it is true, and sits above the affordances it disables — so a toast
   * stack repeating it in the corner is noise. Polling and the terminal
   * refresh are unaffected; only the narration goes away.
   */
  silent?: boolean
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
  const {
    envName,
    onTerminal,
    orgSlug,
    projectId,
    runUrl,
    silent,
    tag,
    toastId,
  } = props

  const settledRef = useRef(false)
  const notify = silent ? SILENT : toast

  const query = useQuery<PromoteStatus>({
    enabled: !settledRef.current,
    queryFn: ({ signal }) => getPromoteStatus(orgSlug, projectId, signal),
    queryKey: ['promote-status', orgSlug, projectId],
    refetchInterval: (q) => {
      if (settledRef.current) return false
      const data = q.state.data
      // Not ours yet (see the effect below) — a terminal status from
      // someone else's promote must not stop this one's polling.
      if (isForAnotherPromote(data, tag)) return 6000
      const status = data?.status
      if (status && TERMINAL_STATES.has(status)) return false
      return 6000
    },
    refetchIntervalInBackground: false,
    retry: 3,
  })

  // The dispatch toast was raised by the mutation, before this watcher
  // and the banner existed, so silence means clearing it too.
  useEffect(() => {
    if (silent) toast.dismiss(toastId)
  }, [silent, toastId])

  useEffect(() => {
    if (settledRef.current) return
    const data = query.data
    if (!data) return
    // Keep the loading toast up and keep polling until the status is
    // actually about this promote.
    if (isForAnotherPromote(data, tag)) return
    // Both sides are plugin-reported, so neither is trusted to reach
    // `window.open` unchecked.
    const url =
      sanitizeHttpUrl(data.artifact_run_url) ?? sanitizeHttpUrl(runUrl)
    const action = url
      ? {
          label: 'View build',
          onClick: () => window.open(url, '_blank', 'noopener'),
        }
      : undefined
    const target = envName ? ` to ${envName}` : ''

    if (data.status === 'building') {
      notify.loading(`Building release ${tag}…`, {
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
      notify.loading(`Deploying ${tag}${target}…`, {
        action,
        icon: <Loader2 className="size-4 animate-spin" />,
        id: toastId,
      })
      return
    }
    if (data.status === 'deploy_failed') {
      settledRef.current = true
      // The build was green, so unlike `build_failed` the release is not
      // blocked — the same tag can be redeployed once the cause is fixed.
      notify.error(`Deploying ${tag}${target} failed`, {
        action,
        description:
          data.error ??
          'The release is not blocked — redeploy this tag once the ' +
            'cause is fixed.',
        icon: <XCircle className="size-4 text-rose-500" />,
        id: toastId,
      })
      onTerminal()
      return
    }
    if (data.status === 'success') {
      settledRef.current = true
      notify.success(envName ? `Released ${tag}${target}` : `Released ${tag}`, {
        action,
        icon: <CheckCircle2 className="size-4 text-emerald-500" />,
        id: toastId,
      })
      onTerminal()
      return
    }
    if (data.status === 'build_failed') {
      settledRef.current = true
      notify.error(`Release build for ${tag} failed`, {
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
      // Nothing failed outright: Imbi lost track of the build, or could
      // not finish after it went green — which now covers losing the
      // rollout too, so this says "promote" rather than "build". The tag
      // is deliberately left shippable either way.
      notify.message(`Lost track of the promote for ${tag}`, {
        action,
        description:
          data.error ??
          'Check the run directly; the tag was not blocked, so it can ' +
            'still be deployed.',
        icon: <Rocket className="size-4" />,
        id: toastId,
      })
      onTerminal()
    }
    // `idle` — nothing recorded yet; keep polling.
  }, [query.data, envName, notify, onTerminal, runUrl, tag, toastId])

  useEffect(() => {
    if (!query.isError || settledRef.current) return
    settledRef.current = true
    const url = sanitizeHttpUrl(runUrl)
    notify.message(`Lost track of the release build for ${tag}`, {
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
  }, [query.isError, notify, onTerminal, runUrl, tag, toastId])

  return null
}

/**
 * True when `data` describes a promote other than the one being watched.
 *
 * `promote-status` is *project*-scoped: it reports whichever promote ran
 * most recently, so between mounting and the server's first write this
 * watcher can be handed the previous promote's terminal status — from a
 * warm query cache, or from a read that lands before the dispatch's own
 * status write. Settling on it would report someone else's outcome
 * against this tag and tear the toast down seconds after the click.
 *
 * A blank tag is treated as ours: the server has written a status but
 * not yet a tag, which is a state of *this* promote, not another one.
 */
function isForAnotherPromote(
  data: PromoteStatus | undefined,
  tag: string,
): boolean {
  return !!data?.tag && data.tag !== tag
}

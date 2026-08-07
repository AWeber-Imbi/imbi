import { useEffect, useRef } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { getPromoteStatus, type PromoteStatus } from '@/api/endpoints'

import type { ReleaseBuildStarted } from './DeploymentModal'

/** Statuses that mean a promote is still running and worth watching. */
const IN_FLIGHT: ReadonlySet<PromoteStatus['status']> = new Set([
  'building',
  'deploying',
])

interface AdoptInFlightPromoteOptions {
  /** Skip the lookup entirely, e.g. before the project id is known. */
  enabled: boolean
  /** Resolves the status' environment *slug* to its display name. */
  envName: (slug: null | string) => null | string
  /** True when this project already has a watcher mounted. */
  hasActiveBuild: boolean
  onBuildStarted: (build: ReleaseBuildStarted) => void
  orgSlug: string
  projectId: string
}

/**
 * Pick up a promote that is already running when this mounts.
 *
 * A promote outlives the page that started it — the build alone takes
 * minutes — but the watcher that follows it is component state, seeded
 * only by the mutation that dispatched it. So a reload, a navigation
 * away and back, or simply opening the project in a second window left
 * the promote unwatched: the server kept driving it to completion while
 * the browser showed nothing and never refreshed when it landed.
 *
 * `promote-status` is project-scoped and already reports the in-flight
 * state, so the fix is to ask on mount rather than to only ever learn
 * about a promote from the click that started it.
 *
 * Deliberately one-shot: it decides once per mount and then stops, so a
 * settled watcher can't be re-adopted from a stale `deploying` still
 * sitting in the query cache, which would spawn watchers forever. The
 * cost is that a promote started in *another* window after this one
 * mounted isn't picked up until the next mount — worth it to keep the
 * adoption rule impossible to get into a loop.
 */
export function useAdoptInFlightPromote({
  enabled,
  envName,
  hasActiveBuild,
  onBuildStarted,
  orgSlug,
  projectId,
}: AdoptInFlightPromoteOptions): void {
  const decidedRef = useRef(false)

  const query = useQuery<PromoteStatus>({
    enabled: enabled && !decidedRef.current,
    queryFn: ({ signal }) => getPromoteStatus(orgSlug, projectId, signal),
    // Deliberately NOT the watcher's ``promote-status`` key. Sharing it
    // seeds that cache entry at page load with whatever promote ran
    // last, and a ``ReleaseBuildWatcher`` mounting later reads it
    // synchronously — settling against the *previous* promote's outcome
    // before its own first fetch resolves. One extra request per mount
    // is the cost of keeping the two from contaminating each other.
    queryKey: ['promote-status-adoption', orgSlug, projectId],
    // A cached status from a previous visit says nothing about now, and
    // the whole point is to catch a promote that started while this page
    // was not mounted.
    refetchOnMount: 'always',
    retry: false,
    staleTime: 0,
  })

  useEffect(() => {
    if (decidedRef.current) return
    const data = query.data
    if (!data) return
    // One shot, whichever way it goes — including "nothing in flight".
    decidedRef.current = true
    if (!IN_FLIGHT.has(data.status)) return
    // The mutation that started this promote already mounted a watcher;
    // adopting here too would double every toast update.
    if (hasActiveBuild) return

    const tag = data.tag ?? 'release'
    const runUrl = data.artifact_run_url ?? null
    const target = envName(data.environment)
    const action = runUrl
      ? {
          label: 'View build',
          onClick: () => window.open(runUrl, '_blank', 'noopener'),
        }
      : undefined
    const toastId = toast.loading(
      data.status === 'building'
        ? `Building release ${tag}…`
        : `Deploying ${tag}${target ? ` to ${target}` : ''}…`,
      {
        action,
        description:
          data.status === 'building'
            ? 'The release workflow is cutting the tag and building.'
            : undefined,
        icon: <Loader2 className="size-4 animate-spin" />,
        id: `promote:${projectId}`,
      },
    )
    onBuildStarted({
      envName: target,
      originOrgSlug: orgSlug,
      originProjectId: projectId,
      runUrl,
      tag,
      toastId,
    })
  }, [query.data, envName, hasActiveBuild, onBuildStarted, orgSlug, projectId])
}

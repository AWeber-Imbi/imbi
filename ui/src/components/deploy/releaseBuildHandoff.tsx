import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { sanitizeHttpUrl } from '@/lib/utils'

import type { ReleaseBuildStarted } from './DeploymentModal'

/**
 * The dispatch-path fields shared by `DeploymentTriggerResponse` (a
 * promote) and `CutReleaseResponse` (a library release cut). Both can
 * come back as a dispatched build, and both need the same handling.
 */
export interface DispatchedBuildResponse {
  artifact_run_url?: null | string
  phase?: 'building' | null
  tag?: null | string
  warning?: null | string
}

interface HandoffOptions {
  /** Target env, or `null` for a release-only cut. */
  envName: null | string
  onBuildStarted?: (build: ReleaseBuildStarted) => void
  orgSlug: string
  projectId: string
  /** Tag to show if the response didn't echo one back. */
  tagFallback: string
}

/**
 * Take over a promote response that dispatched a release build.
 *
 * Returns `true` when it handled the response, so callers can `return`
 * instead of running their normal "there is a Deployment to watch" path.
 * Returns `false` for the inline path, which is unchanged.
 *
 * This exists as a shared helper rather than an inline branch because
 * three separate call sites can receive a dispatched build — the promote
 * modal, the Deployments tab's release train, and the library
 * release-cut card — and each previously assumed its response was
 * either synchronous or carried a watchable Deployment. On the dispatch
 * path neither holds: `run.run_id` is `''` and no release URL exists
 * yet, so a caller that hasn't been taught about `phase` falls straight
 * through to a terminal "Released!" toast minutes before anything ships.
 * Keeping the check in one place means a fourth entry point can't
 * reintroduce that.
 */
export function handleDispatchedBuild(
  data: DispatchedBuildResponse,
  options: HandoffOptions,
): boolean {
  if (data.phase !== 'building') return false
  const { envName, onBuildStarted, orgSlug, projectId, tagFallback } = options
  const tagLabel = data.tag ?? tagFallback
  // Plugin-reported, so it is untrusted input on its way to
  // `window.open`; a `javascript:` URL there runs in this origin.
  const buildUrl = sanitizeHttpUrl(data.artifact_run_url)
  const toastId = toast.loading(`Building release ${tagLabel}…`, {
    action: buildUrl
      ? {
          label: 'View build',
          onClick: () => window.open(buildUrl, '_blank', 'noopener'),
        }
      : undefined,
    description:
      'The release workflow is cutting the tag and building the artifact.',
    icon: <Loader2 className="size-4 animate-spin" />,
  })
  onBuildStarted?.({
    envName,
    originOrgSlug: orgSlug,
    originProjectId: projectId,
    runUrl: buildUrl,
    tag: tagLabel,
    toastId,
  })
  if (data.warning) {
    toast.warning(`Release build for ${tagLabel} needs attention`, {
      description: data.warning,
      duration: 10_000,
    })
  }
  return true
}

/* eslint-disable react-refresh/only-export-components */
import { useQuery } from '@tanstack/react-query'

import { getCommitCheckStatus } from '@/api/endpoints'
import { Alert } from '@/components/ui/alert'
import { Checkbox } from '@/components/ui/checkbox'
import type { DeploymentCommitCiStatus } from '@/types'

interface CiFailureNoticeProps {
  acknowledged: boolean
  /** What the operator is about to do, for the confirmation copy. */
  action: 'promote' | 'release'
  ciStatus: DeploymentCommitCiStatus | undefined
  onAcknowledgedChange: (next: boolean) => void
  sha: null | string
}

/**
 * Danger strip + acknowledgement checkbox shown when the selected commit's
 * CI failed. Renders nothing otherwise.
 *
 * Deliberately an inline strip rather than a confirm dialog: two of the
 * three callers already live inside a `Dialog`, and the warning belongs
 * beside the commit being chosen — an operator should see it while
 * picking, not only after committing to the click.
 */
export function CiFailureNotice({
  acknowledged,
  action,
  ciStatus,
  onAcknowledgedChange,
  sha,
}: CiFailureNoticeProps) {
  if (!ciNeedsAcknowledgement(ciStatus)) return null
  const verb = action === 'promote' ? 'Promote' : 'Release'
  const gerund = action === 'promote' ? 'Promoting' : 'Releasing'
  return (
    <Alert
      title={`CI failed for ${sha?.slice(0, 7) ?? 'this commit'}`}
      variant="danger"
    >
      <div className="flex flex-col gap-2">
        <span>
          The checks on this commit reported a failure. Review them before
          shipping it — {gerund} anyway is still your call, but it will be
          recorded against the release.
        </span>
        <label className="flex w-fit cursor-pointer items-center gap-2 text-xs font-medium">
          <Checkbox
            aria-label={`${verb} anyway despite the failing CI run`}
            checked={acknowledged}
            onCheckedChange={(checked) =>
              onAcknowledgedChange(checked === true)
            }
          />
          {verb} anyway
        </label>
      </div>
    </Alert>
  )
}

/** Whether `status` is the one state that needs an acknowledgement. */
export function ciNeedsAcknowledgement(
  status: DeploymentCommitCiStatus | undefined,
): boolean {
  return status === 'fail'
}

/**
 * Live CI status for one commit.
 *
 * Read from the plugin rather than from the `ci_status` already carried on
 * synced commit rows: this is the same call the API's promote gate makes,
 * so the warning and the gate cannot disagree. A synced status can lag, and
 * a banner that says "green" over a promote the server then refuses is
 * worse than no banner at all.
 *
 * `unknown` is the answer for a project with no CI, a token that cannot
 * read check-runs, and a commit whose checks never ran — none of which the
 * API gates on, so none of which this warns about.
 *
 * `ciPending` is what callers must gate submission on. An unresolved query
 * has no `ci_status`, and "no status" is indistinguishable from `unknown`
 * here — so without it a fast click would submit a failing commit before
 * the answer landed and take a bare 409 instead of the acknowledgement
 * flow. `isLoading` (not `isPending`) is deliberate: a query disabled for
 * a null `sha` is pending forever, and that must not wedge the button —
 * those callers already gate on the missing sha.
 */
export function useCommitCheckStatus(
  orgSlug: string,
  projectId: string,
  sha: null | string,
): { ciPending: boolean; ciStatus: DeploymentCommitCiStatus | undefined } {
  const { data, isLoading } = useQuery({
    enabled: !!orgSlug && !!projectId && !!sha,
    queryFn: ({ signal }) =>
      getCommitCheckStatus(
        orgSlug,
        projectId,
        sha as string,
        undefined,
        signal,
      ),
    queryKey: ['commitCheckStatus', orgSlug, projectId, sha],
  })
  return { ciPending: isLoading, ciStatus: data?.ci_status }
}

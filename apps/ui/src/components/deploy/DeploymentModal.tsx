import { useEffect, useState } from 'react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { DeploymentRunStatus, Environment } from '@/types'

import { DeployTab } from './DeployTab'
import { PromoteTab } from './PromoteTab'

export interface DeploymentRunStarted {
  /**
   * Optional label for the toast action button rendered by the
   * watcher. Lets the originating tab pick between "View run" and
   * "View release" so promotions that only carry a release URL still
   * surface a useful deep-link.
   */
  actionLabel?: string
  /**
   * Optional URL the watcher's toast action should open. Falls back to
   * ``runUrl`` when omitted so existing callers stay correct.
   */
  actionUrl?: null | string
  envName: string
  initialStatus?: DeploymentRunStatus
  /**
   * Org slug the run was triggered from. The watcher uses this rather
   * than the currently-mounted project so polling stays bound to the
   * originating project even if the user navigates away.
   */
  originOrgSlug: string
  /** Project id the run was triggered from. */
  originProjectId: string
  runId: string
  runUrl?: null | string
  toastId: number | string
}

interface ReleaseModalProps {
  canDeploy: boolean
  canPromote: boolean
  environments: Environment[]
  // For the promote tab — the source env (preceding the target) and the
  // committish from its current release.  Required when ``canPromote`` is
  // true; ignored otherwise.
  fromCommittish?: null | string
  fromEnvironment?: string
  initialAction: 'deploy' | 'promote'
  initialEnvSlug: string
  onOpenChange: (open: boolean) => void
  onRunStarted?: (run: DeploymentRunStarted) => void
  open: boolean
  orgSlug: string
  projectId: string
  projectName: string
}

// fallow-ignore-next-line complexity
export function ReleaseModal({
  canDeploy,
  canPromote,
  environments,
  fromCommittish,
  fromEnvironment,
  initialAction,
  initialEnvSlug,
  onOpenChange,
  onRunStarted,
  open,
  orgSlug,
  projectId,
  projectName,
}: ReleaseModalProps) {
  // Lock the active tab to whichever action is actually available so a
  // deep-link to /promote/<env> on an env that no longer supports promote
  // doesn't render an empty pane.
  const resolveTab = (a: 'deploy' | 'promote') =>
    a === 'promote' ? (canPromote ? 'promote' : 'deploy') : 'deploy'
  const [tab, setTab] = useState<'deploy' | 'promote'>(
    resolveTab(initialAction),
  )
  useEffect(() => {
    if (open) setTab(resolveTab(initialAction))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialAction, canDeploy, canPromote])

  const promoteReady = canPromote && !!fromEnvironment
  const description =
    tab === 'promote' && fromEnvironment
      ? `Tag & release ${fromEnvironment} → ${initialEnvSlug}`
      : 'Roll an existing commit or tag onto an environment'

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-w-230 sm:max-w-230">
        <DialogTitle className="sr-only">{`Release ${projectName}`}</DialogTitle>
        <Tabs
          onValueChange={(v) => setTab(v as 'deploy' | 'promote')}
          value={tab}
        >
          <TabsList className="border-tertiary h-auto justify-start gap-6 rounded-none border-b px-6 pt-5">
            {canDeploy ? (
              <TabsTrigger value="deploy">Deploy</TabsTrigger>
            ) : null}
            {canPromote ? (
              <TabsTrigger value="promote">Promote</TabsTrigger>
            ) : null}
          </TabsList>
          <DialogDescription className="px-6 pt-3">
            {description}
          </DialogDescription>
          {canDeploy ? (
            <TabsContent className="px-6 pt-3 pb-4" value="deploy">
              <DeployTab
                environments={environments}
                initialEnvSlug={initialEnvSlug}
                onClose={() => onOpenChange(false)}
                onRunStarted={onRunStarted}
                open={open && tab === 'deploy'}
                orgSlug={orgSlug}
                projectId={projectId}
              />
            </TabsContent>
          ) : null}
          {canPromote ? (
            <TabsContent className="px-6 pt-3 pb-4" value="promote">
              {promoteReady ? (
                <PromoteTab
                  environments={environments}
                  fromCommittish={fromCommittish}
                  fromEnvironment={fromEnvironment as string}
                  onClose={() => onOpenChange(false)}
                  onRunStarted={onRunStarted}
                  open={open && tab === 'promote'}
                  orgSlug={orgSlug}
                  projectId={projectId}
                  toEnvironment={initialEnvSlug}
                />
              ) : (
                <p className="border-secondary text-tertiary rounded-md border border-dashed p-4 text-sm">
                  No upstream environment with a deployed version yet — deploy
                  to an earlier env first.
                </p>
              )}
            </TabsContent>
          ) : null}
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

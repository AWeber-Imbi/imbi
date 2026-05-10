import { GitMerge, Rocket } from 'lucide-react'

import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
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

interface DeployModalProps {
  environments: Environment[]
  initialEnvSlug?: string
  onOpenChange: (open: boolean) => void
  /**
   * Called after a successful trigger so the parent can mount a
   * ``<DeploymentRunWatcher>`` for the run.  Without this prop the
   * tabs fall back to a one-shot success toast (Phase 1 behavior).
   */
  onRunStarted?: (run: DeploymentRunStarted) => void
  open: boolean
  orgSlug: string
  projectId: string
  projectName: string
}

interface PromoteModalProps {
  environments: Environment[]
  fromCommittish?: null | string
  fromEnvironment: string
  onOpenChange: (open: boolean) => void
  onRunStarted?: (run: DeploymentRunStarted) => void
  open: boolean
  orgSlug: string
  projectId: string
  projectName: string
  toEnvironment: string
}

export function DeployModal({
  environments,
  initialEnvSlug,
  onOpenChange,
  onRunStarted,
  open,
  orgSlug,
  projectId,
  projectName,
}: DeployModalProps) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-w-[920px] gap-0 p-0 sm:max-w-[920px]">
        <ModalHeader
          icon={<Rocket className="h-4 w-4" />}
          subtitle="Roll an existing commit or tag onto an environment"
          title={`Deploy ${projectName}`}
        />
        <div className="px-6 py-4">
          <DeployTab
            environments={environments}
            initialEnvSlug={initialEnvSlug}
            onClose={() => onOpenChange(false)}
            onRunStarted={onRunStarted}
            open={open}
            orgSlug={orgSlug}
            projectId={projectId}
          />
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function PromoteModal({
  environments,
  fromCommittish,
  fromEnvironment,
  onOpenChange,
  onRunStarted,
  open,
  orgSlug,
  projectId,
  projectName,
  toEnvironment,
}: PromoteModalProps) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-w-[920px] gap-0 p-0 sm:max-w-[920px]">
        <ModalHeader
          icon={<GitMerge className="h-4 w-4" />}
          subtitle={`Tag & release ${fromEnvironment} → ${toEnvironment}`}
          title={`Promote ${projectName}`}
        />
        <div className="px-6 py-4">
          <PromoteTab
            environments={environments}
            fromCommittish={fromCommittish}
            fromEnvironment={fromEnvironment}
            onClose={() => onOpenChange(false)}
            onRunStarted={onRunStarted}
            open={open}
            orgSlug={orgSlug}
            projectId={projectId}
            toEnvironment={toEnvironment}
          />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ModalHeader({
  icon,
  subtitle,
  title,
}: {
  icon: React.ReactNode
  subtitle: string
  title: string
}) {
  return (
    <header className="border-b border-secondary px-6 py-4">
      <DialogTitle className="flex items-center gap-1.5 text-sm font-medium">
        {icon}
        {title}
      </DialogTitle>
      <p className="mt-0.5 text-xs text-tertiary">{subtitle}</p>
    </header>
  )
}

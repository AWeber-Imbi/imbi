import { GitMerge, Rocket } from 'lucide-react'

import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import type { Environment } from '@/types'

import { DeployTab } from './DeployTab'
import { PromoteTab } from './PromoteTab'

export type DeployModalTab = 'deploy' | 'promote'

interface DeploymentModalProps {
  environments: Environment[]
  initialEnvSlug?: string
  initialTab?: DeployModalTab
  onOpenChange: (open: boolean) => void
  open: boolean
  orgSlug: string
  projectId: string
  projectName: string
  // Promote-tab inputs.  When set together with initialTab='promote'
  // the modal opens directly into the Promote flow with the gap
  // pre-selected (via the popover hand-off) or the testing → next-env
  // gap inferred from the chip click.
  promoteFrom?: null | string
  promoteFromCommittish?: null | string
  promoteTo?: null | string
}

export function DeploymentModal({
  environments,
  initialEnvSlug,
  initialTab = 'deploy',
  onOpenChange,
  open,
  orgSlug,
  projectId,
  projectName,
  promoteFrom,
  promoteFromCommittish,
  promoteTo,
}: DeploymentModalProps) {
  const isPromote = initialTab === 'promote' && !!promoteFrom && !!promoteTo
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-w-[680px] gap-0 p-0 sm:max-w-[680px]">
        <header className="flex items-stretch border-b border-secondary px-6">
          <DialogTitle className="sr-only">
            {isPromote ? `Promote ${projectName}` : `Deploy ${projectName}`}
          </DialogTitle>
          <TabHeader
            active={!isPromote}
            icon={<Rocket className="h-4 w-4" />}
            subtitle="existing version"
            title="Deploy"
          />
          <TabHeader
            active={isPromote}
            icon={<GitMerge className="h-4 w-4" />}
            subtitle="tag & release notes"
            title="Promote"
          />
        </header>
        <div className="px-6 py-4">
          {isPromote ? (
            <PromoteTab
              fromCommittish={promoteFromCommittish}
              fromEnvironment={promoteFrom}
              onClose={() => onOpenChange(false)}
              open={open}
              orgSlug={orgSlug}
              projectId={projectId}
              toEnvironment={promoteTo}
            />
          ) : (
            <DeployTab
              environments={environments}
              initialEnvSlug={initialEnvSlug}
              onClose={() => onOpenChange(false)}
              open={open}
              orgSlug={orgSlug}
              projectId={projectId}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function TabHeader({
  active,
  icon,
  subtitle,
  title,
}: {
  active: boolean
  icon: React.ReactNode
  subtitle: string
  title: string
}) {
  // Headers are presentational — the modal mode is fixed by props at
  // mount time, so mark non-active headers as disabled to make that
  // unambiguous to assistive tech and keyboard users.
  return (
    <div
      aria-current={active ? 'page' : undefined}
      aria-disabled={!active}
      className={cn(
        'flex flex-col py-4 pr-6 text-sm',
        active ? '-mb-px border-b-2 border-action' : 'text-tertiary opacity-60',
      )}
      role="presentation"
    >
      <span className="flex items-center gap-1.5 font-medium">
        {icon}
        {title}
      </span>
      <span className="mt-0.5 text-xs">{subtitle}</span>
    </div>
  )
}

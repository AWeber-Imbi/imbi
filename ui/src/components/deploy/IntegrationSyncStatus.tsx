// The deployment integration this project is wired to, plus the action that
// refreshes what imbi has synced from it. Shared by the Deployments tab
// sidebar and the Releases tab header so both name the integration the same
// way and sync through the same path.
import { Plug, PlugZap, RefreshCw } from 'lucide-react'

import { EntityIcon } from '@/components/ui/entity-icon'
import { Sk } from '@/components/ui/skeleton'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export type Readiness = 'connected' | 'disconnected' | 'error' | 'loading'

interface IntegrationSyncStatusProps {
  className?: string
  connectLabel: string
  isSyncing: boolean
  onSync: () => void
  readiness: Readiness
  /** Third-party service powering the deployment plugin. */
  serviceIcon: null | string
  serviceLabel: null | string
}

export function IntegrationSyncStatus({
  className,
  connectLabel,
  isSyncing,
  onSync,
  readiness,
  serviceIcon,
  serviceLabel,
}: IntegrationSyncStatusProps) {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <ConnectionStatus
        connectLabel={connectLabel}
        readiness={readiness}
        serviceIcon={serviceIcon}
        serviceLabel={serviceLabel}
      />
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              aria-label="Sync commits, tags & releases"
              className="text-tertiary hover:text-primary shrink-0 cursor-pointer rounded p-1 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              disabled={isSyncing}
              onClick={onSync}
              type="button"
            >
              <RefreshCw
                className={cn(isSyncing && 'animate-spin')}
                size={14}
              />
            </button>
          </TooltipTrigger>
          <TooltipContent>
            <p>Sync commits, tags & releases</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  )
}

function ConnectionStatus({
  connectLabel,
  readiness,
  serviceIcon,
  serviceLabel,
}: {
  connectLabel: string
  readiness: Readiness
  serviceIcon: null | string
  serviceLabel: null | string
}) {
  if (readiness === 'connected') {
    return (
      <span className="text-success inline-flex items-center gap-1.5 text-xs">
        {serviceIcon ? (
          <EntityIcon className="size-3.5" icon={serviceIcon} />
        ) : (
          <PlugZap size={13} />
        )}
        {serviceLabel ?? connectLabel}
      </span>
    )
  }
  if (readiness === 'loading') {
    return <Sk line w={148} />
  }
  return (
    <span className="text-tertiary inline-flex items-center gap-1.5 text-xs">
      <Plug size={13} />
      {readiness === 'error'
        ? 'Could not check deployment access'
        : `Connect to ${connectLabel} to enable deployments`}
    </span>
  )
}

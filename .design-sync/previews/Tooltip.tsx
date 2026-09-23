import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from 'imbi-ui'
import { RefreshCw } from 'lucide-react'

export const SyncButton = () => (
  <div className="flex justify-center p-12">
    <TooltipProvider>
      <Tooltip open>
        <TooltipTrigger asChild>
          <button
            aria-label="Sync"
            className="text-secondary hover:bg-secondary inline-flex size-8 items-center justify-center rounded-md border"
            type="button"
          >
            <RefreshCw className="size-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent>
          <p>Sync commits, tags &amp; releases</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  </div>
)

export const Timestamp = () => (
  <div className="flex justify-center p-12">
    <TooltipProvider>
      <Tooltip open>
        <TooltipTrigger asChild>
          <span className="text-tertiary cursor-default font-mono text-xs whitespace-nowrap">
            3 hours ago
          </span>
        </TooltipTrigger>
        <TooltipContent side="bottom">9/23/2026, 9:14:07 AM</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  </div>
)

import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { GitMerge, Loader2 } from 'lucide-react'

import { listPromotionOptions } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import type { PromotionOption } from '@/types'

interface PromoteDialogProps {
  // The Promote button rendered as the trigger.
  children: React.ReactNode
  onOpenChange: (open: boolean) => void
  onPromote: (option: PromotionOption) => void
  open: boolean
  orgSlug: string
  projectId: string
}

export function PromoteDialog({
  children,
  onOpenChange,
  onPromote,
  open,
  orgSlug,
  projectId,
}: PromoteDialogProps) {
  const { data: options = [], isLoading } = useQuery<PromotionOption[]>({
    enabled: open && !!orgSlug && !!projectId,
    queryFn: ({ signal }) =>
      listPromotionOptions(orgSlug, projectId, undefined, signal),
    queryKey: ['promotionOptions', orgSlug, projectId],
  })

  const [selectedSlug, setSelectedSlug] = useState<null | string>(null)
  const selected = useMemo<null | PromotionOption>(() => {
    if (!options.length) return null
    if (!selectedSlug) return options[0]
    return (
      options.find(
        (opt) =>
          `${opt.from_environment}->${opt.to_environment}` === selectedSlug,
      ) ?? options[0]
    )
  }, [options, selectedSlug])

  return (
    <Popover onOpenChange={onOpenChange} open={open}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent align="end" className="w-[360px] p-0">
        <header className="flex items-center gap-2 border-b border-secondary px-4 py-3">
          <GitMerge className="text-action h-4 w-4" />
          <span className="text-sm font-medium">Promote a build</span>
        </header>
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-tertiary">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        ) : options.length === 0 ? (
          <p className="px-4 py-4 text-xs text-tertiary">
            No promotion paths available — at least one environment must have a
            release deployed.
          </p>
        ) : (
          <ul className="px-2 py-2">
            {options.map((opt) => {
              const slug = `${opt.from_environment}->${opt.to_environment}`
              const active =
                slug ===
                (selectedSlug ??
                  `${options[0]?.from_environment}->${options[0]?.to_environment}`)
              return (
                <li key={slug}>
                  <button
                    className={cn(
                      'flex w-full flex-col rounded-md px-2 py-2 text-left text-xs transition-colors',
                      active
                        ? 'border border-action bg-action/5'
                        : 'border border-transparent hover:bg-tertiary/30',
                    )}
                    onClick={() => setSelectedSlug(slug)}
                    type="button"
                  >
                    <span className="text-sm font-medium">
                      {opt.from_environment} → {opt.to_environment}
                    </span>
                    <span className="mt-0.5 text-tertiary">
                      {opt.from_version ? (
                        <>
                          <span className="font-mono">{opt.from_version}</span>
                          {' from '}
                          {opt.from_environment}
                        </>
                      ) : (
                        <>nothing on {opt.from_environment} to promote</>
                      )}
                    </span>
                    <span className="text-tertiary">
                      currently{' '}
                      <span className="font-mono">{opt.to_version ?? '—'}</span>{' '}
                      on {opt.to_environment}
                      {opt.commits_pending != null
                        ? ` · ${opt.commits_pending} commits ahead`
                        : ''}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        <footer className="flex justify-end gap-2 border-t border-secondary px-4 py-3">
          <Button
            onClick={() => onOpenChange(false)}
            size="sm"
            type="button"
            variant="ghost"
          >
            Cancel
          </Button>
          <Button
            disabled={!selected}
            onClick={() => {
              if (selected) onPromote(selected)
            }}
            size="sm"
            type="button"
          >
            Promote
          </Button>
        </footer>
      </PopoverContent>
    </Popover>
  )
}

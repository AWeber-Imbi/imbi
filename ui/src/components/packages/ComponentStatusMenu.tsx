import { Check, ChevronDown } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  Popover,
  PopoverClose,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import type { ComponentStatus } from '@/types'

import { STATUS_LABEL, STATUS_OPTIONS, STATUS_VARIANT } from './status'

interface ComponentStatusMenuProps {
  disabled?: boolean
  label: string
  onSelect: (status: ComponentStatus | null) => void
  status: ComponentStatus | null | undefined
}

/**
 * Governance picker over the two marks, plus clearing.
 *
 * Unmarked is not a third mark -- it is `null`, and it renders as
 * "Set status" so the row reads as un-reviewed rather than as
 * reviewed-and-approved. Clearing is offered only once something is
 * set, since there is nothing to undo otherwise.
 */
export function ComponentStatusMenu({
  disabled,
  label,
  onSelect,
  status,
}: ComponentStatusMenuProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          aria-label={label}
          className="inline-flex items-center gap-1 disabled:opacity-50"
          disabled={disabled}
          type="button"
        >
          {status ? (
            <Badge variant={STATUS_VARIANT[status]}>
              {STATUS_LABEL[status]}
            </Badge>
          ) : (
            <span className="border-tertiary text-tertiary hover:text-secondary inline-flex h-5 items-center rounded border px-1.5 text-[11px] whitespace-nowrap">
              Set status
            </span>
          )}
          <ChevronDown className="text-tertiary size-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-44 p-1">
        <div className="flex items-center justify-between gap-2 px-2 py-1">
          <p className="text-secondary text-xs font-medium tracking-wide uppercase">
            {label}
          </p>
          {status && (
            <PopoverClose asChild>
              <button
                className="text-action text-xs"
                onClick={() => onSelect(null)}
                type="button"
              >
                Clear
              </button>
            </PopoverClose>
          )}
        </div>
        {STATUS_OPTIONS.map((option) => (
          <PopoverClose asChild key={option}>
            <button
              className="hover:bg-secondary flex w-full items-center gap-2 rounded px-2 py-1.5 text-left"
              onClick={() => onSelect(option)}
              type="button"
            >
              <Check
                className={`size-3 ${option === status ? 'text-action' : 'opacity-0'}`}
              />
              <Badge variant={STATUS_VARIANT[option]}>
                {STATUS_LABEL[option]}
              </Badge>
            </button>
          </PopoverClose>
        ))}
      </PopoverContent>
    </Popover>
  )
}

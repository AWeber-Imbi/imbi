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
import type { StatusValue } from './status'

interface ComponentStatusMenuProps {
  disabled?: boolean
  label: string
  onSelect: (status: StatusValue) => void
  status: ComponentStatus | null | undefined
}

/**
 * Tri-state governance picker. "Current" is offered as an option even
 * though it is stored as the absence of a mark — an operator undoing a
 * mark looks for the state to return to, not for a "clear" verb.
 */
export function ComponentStatusMenu({
  disabled,
  label,
  onSelect,
  status,
}: ComponentStatusMenuProps) {
  const current: StatusValue = status ?? 'current'
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          aria-label={label}
          className="inline-flex items-center gap-1 disabled:opacity-50"
          disabled={disabled}
          type="button"
        >
          <Badge variant={STATUS_VARIANT[current]}>
            {STATUS_LABEL[current]}
          </Badge>
          <ChevronDown className="text-tertiary size-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-44 p-1">
        <p className="text-secondary px-2 py-1 text-xs font-medium tracking-wide uppercase">
          {label}
        </p>
        {STATUS_OPTIONS.map((option) => (
          <PopoverClose asChild key={option}>
            <button
              className="hover:bg-secondary flex w-full items-center gap-2 rounded px-2 py-1.5 text-left"
              onClick={() => onSelect(option)}
              type="button"
            >
              <Check
                className={`size-3 ${option === current ? 'text-action' : 'opacity-0'}`}
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

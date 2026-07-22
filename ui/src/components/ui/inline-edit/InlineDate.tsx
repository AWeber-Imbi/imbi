import { useState } from 'react'

import { DayPicker } from 'react-day-picker'
import 'react-day-picker/dist/style.css'
import { toast } from 'sonner'

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'

import { InlineDisplay } from './InlineDisplay'

export interface InlineDateProps {
  /** 'date' → YYYY-MM-DD, 'date-time' → ISO 8601 string */
  mode?: 'date' | 'date-time'
  onCommit: (next: null | string) => Promise<void> | void
  pending?: boolean
  placeholder?: string
  readOnly?: boolean
  /** Override the display-mode rendering. */
  renderDisplay?: React.ReactNode
  value: null | string
}

export function InlineDate({
  mode = 'date',
  onCommit,
  pending = false,
  placeholder,
  readOnly = false,
  renderDisplay,
  value,
}: InlineDateProps) {
  const [open, setOpen] = useState(false)
  const current = value ? new Date(value) : undefined
  const hasValid = !!current && !Number.isNaN(current.getTime())

  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <span>
          <InlineDisplay
            hasValue={hasValid}
            onClick={() => setOpen(true)}
            pending={pending}
            placeholder={placeholder}
            readOnly={readOnly}
          >
            {renderDisplay ?? (hasValid && current!.toLocaleDateString())}
          </InlineDisplay>
        </span>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-2">
        <DayPicker
          defaultMonth={hasValid ? current : undefined}
          mode="single"
          onSelect={async (d) => {
            setOpen(false)
            if (!d) return
            try {
              await onCommit(toIso(d, mode))
            } catch (e) {
              toast.error(e instanceof Error ? e.message : 'Save failed')
            }
          }}
          selected={hasValid ? current : undefined}
        />
      </PopoverContent>
    </Popover>
  )
}

function toIso(d: Date, mode: 'date' | 'date-time'): string {
  if (mode === 'date') return d.toISOString().slice(0, 10)
  return d.toISOString()
}

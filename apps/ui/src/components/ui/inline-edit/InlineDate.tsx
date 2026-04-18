import { useState } from 'react'
import { DayPicker } from 'react-day-picker'
import 'react-day-picker/dist/style.css'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { InlineDisplay } from './InlineDisplay'
import { toast } from 'sonner'

export interface InlineDateProps {
  value: string | null
  onCommit: (next: string | null) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
  /** 'date' → YYYY-MM-DD, 'date-time' → ISO 8601 string */
  mode?: 'date' | 'date-time'
  /** Override the display-mode rendering. */
  renderDisplay?: React.ReactNode
}

function toIso(d: Date, mode: 'date' | 'date-time'): string {
  if (mode === 'date') return d.toISOString().slice(0, 10)
  return d.toISOString()
}

export function InlineDate({
  value,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder,
  mode = 'date',
  renderDisplay,
}: InlineDateProps) {
  const [open, setOpen] = useState(false)
  const current = value ? new Date(value) : undefined
  const hasValid = !!current && !Number.isNaN(current.getTime())

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <span>
          <InlineDisplay
            hasValue={hasValid}
            readOnly={readOnly}
            pending={pending}
            onClick={() => setOpen(true)}
            placeholder={placeholder}
          >
            {renderDisplay ?? (hasValid && current!.toLocaleDateString())}
          </InlineDisplay>
        </span>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-2" align="start">
        <DayPicker
          mode="single"
          selected={hasValid ? current : undefined}
          onSelect={async (d) => {
            setOpen(false)
            if (!d) return
            try {
              await onCommit(toIso(d, mode))
            } catch (e) {
              toast.error(e instanceof Error ? e.message : 'Save failed')
            }
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

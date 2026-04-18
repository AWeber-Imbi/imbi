import { useState } from 'react'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { InlineDisplay } from './InlineDisplay'
import { toast } from 'sonner'

export interface InlineMultiSelectOption {
  value: string
  label: string
}

export interface InlineMultiSelectProps {
  values: string[]
  options: InlineMultiSelectOption[]
  onCommit: (next: string[]) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
}

export function InlineMultiSelect({
  values,
  options,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder = 'Select…',
}: InlineMultiSelectProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<string[]>(values)

  const toggle = (v: string) => {
    setDraft((cur) =>
      cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v],
    )
  }

  const sameSet = (a: string[], b: string[]) =>
    a.length === b.length && a.every((x) => b.includes(x))

  const close = async () => {
    setOpen(false)
    if (sameSet(draft, values)) return
    try {
      await onCommit(draft)
    } catch (e) {
      setDraft(values)
      toast.error(e instanceof Error ? e.message : 'Save failed')
    }
  }

  const currentLabels = options
    .filter((o) => values.includes(o.value))
    .map((o) => o.label)
    .join(', ')

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setDraft(values)
          setOpen(true)
        } else {
          void close()
        }
      }}
    >
      <PopoverTrigger asChild>
        <span>
          <InlineDisplay
            hasValue={values.length > 0}
            readOnly={readOnly}
            pending={pending}
            onClick={() => setOpen(true)}
            placeholder={placeholder}
          >
            <span className="text-sm text-primary">{currentLabels}</span>
          </InlineDisplay>
        </span>
      </PopoverTrigger>
      <PopoverContent
        className="max-h-[min(24rem,60vh)] w-56 overflow-y-auto p-2"
        align="end"
      >
        <ul className="space-y-1">
          {options.map((o) => {
            const checked = draft.includes(o.value)
            const id = `multi-${o.value}`
            return (
              <li
                key={o.value}
                className="hover:bg-secondary/50 flex items-center gap-2 rounded-sm px-2 py-1.5"
              >
                <Checkbox
                  id={id}
                  checked={checked}
                  onCheckedChange={() => toggle(o.value)}
                />
                <Label
                  htmlFor={id}
                  className="flex-1 cursor-pointer text-sm font-normal"
                >
                  {o.label}
                </Label>
              </li>
            )
          })}
        </ul>
      </PopoverContent>
    </Popover>
  )
}

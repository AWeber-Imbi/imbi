import { useState } from 'react'

import { toast } from 'sonner'

import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'

import { InlineDisplay } from './InlineDisplay'

export interface InlineMultiSelectOption {
  label: string
  value: string
}

export interface InlineMultiSelectProps {
  onCommit: (next: string[]) => Promise<void> | void
  options: InlineMultiSelectOption[]
  pending?: boolean
  placeholder?: string
  readOnly?: boolean
  values: string[]
}

export function InlineMultiSelect({
  onCommit,
  options,
  pending = false,
  placeholder = 'Select…',
  readOnly = false,
  values,
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
      onOpenChange={(next) => {
        if (next) {
          setDraft(values)
          setOpen(true)
        } else {
          void close()
        }
      }}
      open={open}
    >
      <PopoverTrigger asChild>
        <span>
          <InlineDisplay
            hasValue={values.length > 0}
            onClick={() => setOpen(true)}
            pending={pending}
            placeholder={placeholder}
            readOnly={readOnly}
          >
            <span className="text-sm text-primary">{currentLabels}</span>
          </InlineDisplay>
        </span>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="max-h-[min(24rem,60vh)] w-56 overflow-y-auto p-2"
      >
        <ul className="space-y-1">
          {options.map((o) => {
            const checked = draft.includes(o.value)
            const id = `multi-${o.value}`
            return (
              <li
                className="hover:bg-secondary/50 flex items-center gap-2 rounded-sm px-2 py-1.5"
                key={o.value}
              >
                <Checkbox
                  checked={checked}
                  id={id}
                  onCheckedChange={() => toggle(o.value)}
                />
                <Label
                  className="flex-1 cursor-pointer text-sm font-normal"
                  htmlFor={id}
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

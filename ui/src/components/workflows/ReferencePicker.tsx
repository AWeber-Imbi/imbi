import { type ChangeEvent, type SyntheticEvent, useRef, useState } from 'react'

import { Braces } from 'lucide-react'

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

import { insertReference, type ReferenceGroup } from './references'

type TextElement = HTMLInputElement | HTMLTextAreaElement

export function TemplateInput({
  className,
  groups,
  id,
  multiline,
  onChange,
  value,
}: {
  className?: string
  groups: ReferenceGroup[]
  id: string
  multiline: boolean
  onChange: (value: string) => void
  value: string
}) {
  const element = useRef<null | TextElement>(null)
  const insert = (path: string) => {
    const target = element.current
    const next = insertReference(
      value,
      path,
      target && [
        target.selectionStart ?? value.length,
        target.selectionEnd ?? value.length,
      ],
    )
    onChange(next.value)
    requestAnimationFrame(() => {
      target?.focus()
      target?.setSelectionRange(next.caret, next.caret)
    })
  }
  const props = {
    className: cn(groups.length > 0 && 'pr-10', className),
    id,
    onChange: (event: ChangeEvent<TextElement>) => onChange(event.target.value),
    onSelect: (event: SyntheticEvent<TextElement>) => {
      element.current = event.currentTarget
    },
    value,
  }
  return (
    <div className="relative">
      {multiline ? <Textarea {...props} rows={4} /> : <Input {...props} />}
      {groups.length > 0 && <ReferencePicker groups={groups} onPick={insert} />}
    </div>
  )
}

function GroupHeading({ group }: { group: ReferenceGroup }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="truncate">{group.title}</span>
      {group.mayNotRun && (
        <span
          className="bg-amber-bg text-amber-text rounded-sm px-1 text-[10px]"
          title="This step is not on every path to this one, so its values can be empty."
        >
          may not run
        </span>
      )}
    </span>
  )
}

function ReferencePicker({
  groups,
  onPick,
}: {
  groups: ReferenceGroup[]
  onPick: (path: string) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-label="Insert a reference"
          className="text-tertiary hover:bg-secondary hover:text-primary absolute top-1.5 right-1.5 flex size-7 items-center justify-center rounded-md"
          title="Insert a reference"
          type="button"
        >
          <Braces className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[32rem] max-w-[calc(100vw-2rem)] p-0"
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        <Command>
          <CommandInput placeholder="Search references…" />
          <CommandList>
            <CommandEmpty>No reference matches that search.</CommandEmpty>
            {groups.map((group) => (
              <CommandGroup
                heading={<GroupHeading group={group} />}
                key={group.key}
              >
                {group.references.map((reference) => (
                  <CommandItem
                    key={reference.path}
                    keywords={[group.title]}
                    onSelect={() => {
                      onPick(reference.path)
                      setOpen(false)
                    }}
                    value={reference.path}
                  >
                    <span className="min-w-0 flex-1 font-mono text-xs break-all">
                      {reference.path}
                    </span>
                    <span className="text-tertiary shrink-0 self-start font-mono text-xs whitespace-nowrap">
                      {reference.type}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

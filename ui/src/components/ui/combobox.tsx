import { useState } from 'react'

import { Check, ChevronsUpDown, Plus } from 'lucide-react'

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { cn } from '@/lib/utils'

export interface ComboboxOption {
  label: string
  value: string
}

interface ComboboxProps {
  creatable?: boolean
  disabled?: boolean
  /** Set on the trigger so a `<Label htmlFor>` names the combobox. */
  id?: string
  onChange: (value: string) => void
  options: readonly ComboboxOption[]
  placeholder?: string
  value: string
}

export function Combobox({
  creatable = false,
  disabled = false,
  id,
  onChange,
  options,
  placeholder = 'Select...',
  value,
}: ComboboxProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')

  const selectedLabel =
    options.find((o) => o.value === value)?.label ??
    (creatable && value ? value : undefined)
  const typed = query.trim()
  const canCreate =
    creatable && typed !== '' && !options.some((o) => o.value === typed)
  const changeOpen = (next: boolean) => {
    setOpen(next)
    setQuery('')
  }
  const choose = (next: string) => {
    onChange(next)
    changeOpen(false)
  }

  return (
    <Popover modal onOpenChange={changeOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-expanded={open}
          className={cn(
            'flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:outline-none',
            !selectedLabel && 'text-muted-foreground',
            disabled && 'cursor-not-allowed opacity-50',
          )}
          disabled={disabled}
          id={id}
          role="combobox"
          type="button"
        >
          <span className="truncate">{selectedLabel ?? placeholder}</span>
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="p-0"
        style={{ width: 'var(--radix-popover-trigger-width)' }}
      >
        <Command>
          <CommandInput
            onValueChange={setQuery}
            placeholder="Search..."
            value={query}
          />
          <CommandList>
            {!canCreate && <CommandEmpty>No results found.</CommandEmpty>}
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option.value}
                  onSelect={() => choose(option.value)}
                  value={option.label}
                >
                  <Check
                    className={cn(
                      'size-4',
                      value === option.value ? 'opacity-100' : 'opacity-0',
                    )}
                  />
                  {option.label}
                </CommandItem>
              ))}
            </CommandGroup>
            {canCreate && (
              <CommandGroup forceMount>
                <CommandItem
                  forceMount
                  onSelect={() => choose(typed)}
                  value={`create:${typed}`}
                >
                  <Plus className="size-4" />
                  Use “{typed}”
                </CommandItem>
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

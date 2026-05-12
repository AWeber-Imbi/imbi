import { useState } from 'react'

import { Check, ChevronsUpDown } from 'lucide-react'

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
  disabled?: boolean
  onChange: (value: string) => void
  options: ComboboxOption[]
  placeholder?: string
  value: string
}

export function Combobox({
  disabled = false,
  onChange,
  options,
  placeholder = 'Select...',
  value,
}: ComboboxProps) {
  const [open, setOpen] = useState(false)

  const selectedLabel = options.find((o) => o.value === value)?.label

  return (
    <Popover modal onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-expanded={open}
          className={cn(
            'flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
            !selectedLabel && 'text-muted-foreground',
            disabled && 'cursor-not-allowed opacity-50',
          )}
          disabled={disabled}
          role="combobox"
          type="button"
        >
          <span className="truncate">{selectedLabel ?? placeholder}</span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="p-0"
        style={{ width: 'var(--radix-popover-trigger-width)' }}
      >
        <Command>
          <CommandInput placeholder={`Search...`} />
          <CommandList>
            <CommandEmpty>No results found.</CommandEmpty>
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option.value}
                  onSelect={() => {
                    onChange(option.value)
                    setOpen(false)
                  }}
                  value={option.label}
                >
                  <Check
                    className={cn(
                      'h-4 w-4',
                      value === option.value ? 'opacity-100' : 'opacity-0',
                    )}
                  />
                  {option.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

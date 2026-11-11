import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Plus, X } from 'lucide-react'
import { toast } from 'sonner'

import { createTag, listTags } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
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
import { extractApiErrorDetail } from '@/lib/apiError'
import { LABEL_SWATCHES } from '@/lib/chip-colors'
import { cn } from '@/lib/utils'
import type { Tag } from '@/types'

import type { AgentTagChip } from './agentDraft'
import { AgentLabelChip } from './AgentLabelChip'

interface AgentLabelPickerProps {
  onChange: (tags: AgentTagChip[]) => void
  orgSlug: string
  value: AgentTagChip[]
}

/**
 * Labels are org tags. Pick an existing tag, or create one with a color
 * from the label palette (or no color).
 */
export function AgentLabelPicker({
  onChange,
  orgSlug,
  value,
}: AgentLabelPickerProps) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [color, setColor] = useState<null | string>(LABEL_SWATCHES[4].hex)
  const tagsKey = ['tags', orgSlug] as const

  const { data: tags = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listTags(orgSlug, signal),
    queryKey: tagsKey,
  })

  const add = (tag: Tag) => {
    onChange([...value, { color: tag.color, name: tag.name, slug: tag.slug }])
    setQuery('')
  }

  const create = useMutation({
    mutationFn: () => createTag(orgSlug, { color, name: query.trim() }),
    onError: (error) =>
      toast.error(
        `Failed to create the label: ${extractApiErrorDetail(error)}`,
      ),
    onSuccess: (tag) => {
      queryClient.setQueryData<Tag[]>(tagsKey, (prev) => [...(prev ?? []), tag])
      add(tag)
    },
  })

  const selected = new Set(value.map((t) => t.slug))
  const q = query.trim().toLowerCase()
  const exists = tags.some((t) => t.name.toLowerCase() === q)

  return (
    <div className="flex min-h-10 flex-wrap items-center gap-2">
      {value.map((tag) => (
        <AgentLabelChip key={tag.slug} tag={tag}>
          <button
            aria-label={`Remove label ${tag.name}`}
            className="ml-1 inline-flex opacity-70 hover:opacity-100"
            onClick={() => onChange(value.filter((t) => t.slug !== tag.slug))}
            type="button"
          >
            <X className="size-3" />
          </button>
        </AgentLabelChip>
      ))}
      <Popover onOpenChange={setOpen} open={open}>
        <PopoverTrigger asChild>
          <Button size="sm" type="button" variant="outline">
            Add label
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-72 p-0">
          <Command>
            <CommandInput
              onValueChange={setQuery}
              placeholder="Find or create a label"
              value={query}
            />
            <CommandList>
              <CommandEmpty>No labels match.</CommandEmpty>
              <CommandGroup>
                {tags
                  .filter((t) => !selected.has(t.slug))
                  .map((t) => (
                    <CommandItem
                      key={t.slug}
                      onSelect={() => add(t)}
                      value={t.name}
                    >
                      <AgentLabelChip tag={t} />
                    </CommandItem>
                  ))}
              </CommandGroup>
            </CommandList>
          </Command>
          {q && !exists && (
            <div className="border-tertiary flex flex-col gap-2 border-t p-3">
              <div className="text-overline text-tertiary uppercase">
                New label color
              </div>
              <div
                aria-label="Label color"
                className="flex flex-wrap gap-1.5"
                role="radiogroup"
              >
                <SwatchButton
                  checked={color === null}
                  label="No color"
                  onClick={() => setColor(null)}
                />
                {LABEL_SWATCHES.map((s) => (
                  <SwatchButton
                    checked={color === s.hex}
                    hex={s.hex}
                    key={s.hex}
                    label={s.name}
                    onClick={() => setColor(s.hex)}
                  />
                ))}
              </div>
              <Button
                disabled={create.isPending}
                onClick={() => create.mutate()}
                size="sm"
                type="button"
              >
                <Plus className="mr-1 size-3.5" />
                Create “{query.trim()}”
              </Button>
            </div>
          )}
        </PopoverContent>
      </Popover>
    </div>
  )
}

function SwatchButton({
  checked,
  hex,
  label,
  onClick,
}: {
  checked: boolean
  hex?: string
  label: string
  onClick: () => void
}) {
  return (
    <button
      aria-checked={checked}
      aria-label={label}
      className={cn(
        'flex size-6 items-center justify-center rounded-md border-2',
        checked ? 'border-primary' : 'border-transparent',
        !hex && 'bg-secondary',
      )}
      onClick={onClick}
      role="radio"
      style={hex ? { backgroundColor: hex } : undefined}
      title={label}
      type="button"
    >
      {checked && <Check className={cn('size-3', hex && 'text-white')} />}
    </button>
  )
}

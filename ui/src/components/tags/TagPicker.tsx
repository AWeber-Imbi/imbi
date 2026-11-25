import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { toast } from 'sonner'

import { createOrFindTag, listTags } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { LabelSwatchPicker } from '@/components/ui/label-swatch-picker'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { extractApiErrorDetail } from '@/lib/apiError'
import { LABEL_SWATCHES } from '@/lib/chip-colors'
import { queryKeys } from '@/lib/queryKeys'
import type { Tag } from '@/types'

import { type ChipTag, TagChip } from './TagChip'

interface TagPickerProps {
  onChange: (tags: ChipTag[]) => void
  orgSlug: string
  value: ChipTag[]
}

/**
 * Pick org tags: an existing tag, or a new one with a color from the
 * chip palette (or no color).
 */
export function TagPicker({ onChange, orgSlug, value }: TagPickerProps) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [color, setColor] = useState<null | string>(LABEL_SWATCHES[4].hex)
  const tagsKey = queryKeys.tags(orgSlug)

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
    mutationFn: () => createOrFindTag(orgSlug, { color, name: query.trim() }),
    onError: (error) =>
      toast.error(`Failed to create the tag: ${extractApiErrorDetail(error)}`),
    onSuccess: (tag) => {
      queryClient.invalidateQueries({ queryKey: tagsKey })
      if (!selected.has(tag.slug)) add(tag)
    },
  })

  const selected = new Set(value.map((t) => t.slug))
  const q = query.trim().toLowerCase()
  const exists = tags.some((t) => t.name.toLowerCase() === q)

  return (
    <div className="flex min-h-10 flex-wrap items-center gap-2">
      {value.map((tag) => (
        <TagChip key={tag.slug} tag={tag}>
          <button
            aria-label={`Remove tag ${tag.name}`}
            className="ml-1 inline-flex opacity-70 hover:opacity-100"
            onClick={() => onChange(value.filter((t) => t.slug !== tag.slug))}
            type="button"
          >
            <X className="size-3" />
          </button>
        </TagChip>
      ))}
      <Popover onOpenChange={setOpen} open={open}>
        <PopoverTrigger asChild>
          <Button size="sm" type="button" variant="outline">
            Add tag
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-72 p-0">
          <Command>
            <CommandInput
              onValueChange={setQuery}
              placeholder="Find or create a tag"
              value={query}
            />
            <CommandList>
              <CommandEmpty>No tags match.</CommandEmpty>
              <CommandGroup>
                {tags
                  .filter((t) => !selected.has(t.slug))
                  .map((t) => (
                    <CommandItem
                      key={t.slug}
                      onSelect={() => add(t)}
                      value={t.name}
                    >
                      <TagChip tag={t} />
                    </CommandItem>
                  ))}
              </CommandGroup>
            </CommandList>
          </Command>
          {q && !exists && (
            <div className="border-tertiary flex flex-col gap-2 border-t p-3">
              <div className="text-overline text-tertiary uppercase">
                New tag color
              </div>
              <LabelSwatchPicker
                label="Tag color"
                onChange={setColor}
                value={color}
              />
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

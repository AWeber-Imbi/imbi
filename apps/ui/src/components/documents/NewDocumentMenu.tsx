import { useQuery } from '@tanstack/react-query'
import { ChevronDown, FilePlus2, Plus, StickyNote } from 'lucide-react'

import { listDocumentTemplates } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { EntityIcon } from '@/components/ui/entity-icon'
import { cn } from '@/lib/utils'
import type { DocumentTemplate } from '@/types'

import { filterTemplatesByProjectType } from './documentsHelpers'
import { DocumentTagChip } from './DocumentTagChip'

interface Props {
  className?: string
  onCreate: (template?: DocumentTemplate) => void
  orgSlug: string
  projectTypeSlugs?: string[]
}

const ITEM_CLASS =
  'flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2'

/**
 * "New document" control on the populated Documents tab. Opens a menu led by a
 * blank-document option (today's one-click default), then lists the templates
 * available to this project. When there are no templates it degrades to a plain
 * button that creates a blank document directly.
 */
export function NewDocumentMenu({
  className,
  onCreate,
  orgSlug,
  projectTypeSlugs,
}: Props) {
  const { data: templates = [], isLoading } = useQuery<DocumentTemplate[]>({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listDocumentTemplates(orgSlug, signal),
    queryKey: ['documentTemplates', orgSlug],
  })

  const visibleTemplates = filterTemplatesByProjectType(
    templates,
    projectTypeSlugs,
  )

  // Nothing to choose between — keep the fast path as a plain button.
  // (On error we get no templates, so degrade rather than show an empty menu.)
  if (!isLoading && visibleTemplates.length === 0) {
    return (
      <Button
        className={cn('gap-1.5', className)}
        onClick={() => onCreate()}
        size="sm"
      >
        <Plus className="size-3" />
        New document
      </Button>
    )
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button className={cn('group gap-1.5', className)} size="sm">
          <Plus className="size-3" />
          New document
          <ChevronDown className="size-3 transition-transform duration-150 group-data-[state=open]:rotate-180" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 p-1.5">
        <BlankDocumentItem onSelect={() => onCreate()} />
        <TemplateMenuList onSelect={onCreate} templates={visibleTemplates} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function BlankDocumentItem({ onSelect }: { onSelect: () => void }) {
  return (
    <DropdownMenuItem className={ITEM_CLASS} onSelect={onSelect}>
      <FilePlus2 className="text-secondary size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="text-primary text-[13.5px] font-medium">
          Blank document
        </div>
        <div className="text-tertiary text-xs">Start from an empty editor</div>
      </div>
    </DropdownMenuItem>
  )
}

function TemplateIcon({ icon }: { icon?: null | string }) {
  if (icon) return <EntityIcon className="size-4" icon={icon} />
  return <StickyNote className="size-4" />
}

function TemplateMenuItem({
  onSelect,
  template,
}: {
  onSelect: (template: DocumentTemplate) => void
  template: DocumentTemplate
}) {
  return (
    <DropdownMenuItem
      className={ITEM_CLASS}
      onSelect={() => onSelect(template)}
    >
      <span className="text-secondary inline-flex size-4 shrink-0 items-center justify-center">
        <TemplateIcon icon={template.icon} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-primary text-[13.5px] font-medium">
          {template.name}
        </div>
        {template.description && (
          <div className="text-tertiary truncate text-xs">
            {template.description}
          </div>
        )}
      </div>
      {!!template.tags?.length && (
        <DocumentTagChip size="sm" tag={template.tags[0]} />
      )}
    </DropdownMenuItem>
  )
}

function TemplateMenuList({
  onSelect,
  templates,
}: {
  onSelect: (template: DocumentTemplate) => void
  templates: DocumentTemplate[]
}) {
  if (templates.length === 0) return null
  return (
    <>
      <DropdownMenuSeparator className="bg-tertiary mx-2" />
      <DropdownMenuLabel className="text-overline text-tertiary px-2.5 pt-1 pb-1.5 uppercase">
        From a template
      </DropdownMenuLabel>
      {templates.map((t) => (
        <TemplateMenuItem key={t.id} onSelect={onSelect} template={t} />
      ))}
    </>
  )
}

import { useQuery } from '@tanstack/react-query'
import { Plus, StickyNote } from 'lucide-react'

import { listDocumentTemplates } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { EntityIcon } from '@/components/ui/entity-icon'
import type { DocumentTemplate } from '@/types'

import { DocumentTagChip } from './DocumentTagChip'

interface Props {
  onCreate: (template?: DocumentTemplate) => void
  orgSlug: string
  projectTypeSlugs?: string[]
}

export function DocumentsPinboardEmpty({
  onCreate,
  orgSlug,
  projectTypeSlugs,
}: Props) {
  const {
    data: templates = [],
    error: templatesError,
    isLoading: templatesLoading,
  } = useQuery<DocumentTemplate[]>({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listDocumentTemplates(orgSlug, signal),
    queryKey: ['documentTemplates', orgSlug],
  })

  const projectTypeSet =
    projectTypeSlugs && projectTypeSlugs.length
      ? new Set(projectTypeSlugs)
      : undefined

  const visibleTemplates = templates.filter((t) => {
    if (!t.project_type_slugs || t.project_type_slugs.length === 0) return true
    if (!projectTypeSet) return false
    return t.project_type_slugs.some((s) => projectTypeSet.has(s))
  })

  return (
    <div className="border-tertiary bg-primary flex flex-col items-center gap-4 rounded-lg border px-10 py-14 text-center">
      <div className="relative flex size-27 items-center justify-center">
        <div className="border-tertiary bg-secondary absolute inset-[18px] rotate-[-7deg] rounded-[10px] border" />
        <div className="border-tertiary bg-primary absolute inset-[14px] rotate-[4deg] rounded-[10px] border shadow-sm" />
        <div className="border-warning bg-warning text-warning relative inline-flex size-17 items-center justify-center rounded-xl border">
          <StickyNote className="size-7" />
        </div>
      </div>

      <h2 className="text-h2 m-0 font-medium tracking-[-0.015em]">
        No documents yet for this project
      </h2>
      <p className="text-secondary m-0 max-w-180 text-sm leading-[1.6]">
        Documents capture decisions, reviews, and patterns that outlive any one
        deploy. They render as Markdown, carry tags you can filter, and can be
        pinned to stay at the top of this tab. Documents are also exposed to
        agents in the graph, providing project-level context across your
        workflows.
      </p>

      <Button className="mt-1 gap-1.5" onClick={() => onCreate()}>
        <Plus className="size-3" />
        New document
      </Button>

      {templatesLoading && (
        <div className="text-tertiary mt-5 text-xs">Loading templates…</div>
      )}
      {templatesError && (
        <div className="text-danger mt-5 text-xs">
          Failed to load templates.
        </div>
      )}
      {!templatesLoading && !templatesError && visibleTemplates.length > 0 && (
        <>
          <div className="text-overline text-tertiary mt-5 w-full max-w-216 uppercase">
            Or choose a template
          </div>
          <div className="flex w-full max-w-216 flex-wrap justify-center gap-2.5 text-left">
            {visibleTemplates.map((t) => (
              <button
                className="border-tertiary bg-primary hover:border-secondary flex w-70.25 cursor-pointer flex-col gap-1.5 rounded-lg border p-3.5 text-left hover:shadow-sm"
                key={t.id}
                onClick={() => onCreate(t)}
                type="button"
              >
                <div className="flex items-center gap-2">
                  <div className="bg-secondary text-secondary inline-flex size-6.5 items-center justify-center rounded-md">
                    {t.icon ? (
                      <EntityIcon className="size-3.5" icon={t.icon} />
                    ) : (
                      <StickyNote className="size-3.5" />
                    )}
                  </div>
                  <span className="text-primary text-[13.5px] font-medium">
                    {t.name}
                  </span>
                  {t.tags && t.tags.length > 0 && (
                    <span className="ml-auto">
                      <DocumentTagChip size="sm" tag={t.tags[0]} />
                    </span>
                  )}
                </div>
                {t.description && (
                  <div className="text-tertiary text-xs leading-normal">
                    {t.description}
                  </div>
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

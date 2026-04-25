import { Plus, StickyNote } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { NoteTagChip } from './NoteTagChip'
import { NOTE_TEMPLATES } from './notesTemplates'

interface Props {
  onCreate: (templateSlug?: string) => void
}

export function NotesPinboardEmpty({ onCreate }: Props) {
  return (
    <div className="flex flex-col items-center gap-4 rounded-lg border border-tertiary bg-primary px-10 py-14 text-center">
      <div className="relative flex h-[108px] w-[108px] items-center justify-center">
        <div className="absolute inset-[18px] -rotate-[7deg] rounded-[10px] border border-tertiary bg-secondary" />
        <div className="absolute inset-[14px] rotate-[4deg] rounded-[10px] border border-tertiary bg-primary shadow-sm" />
        <div className="relative inline-flex h-[68px] w-[68px] items-center justify-center rounded-xl border border-warning bg-warning text-warning">
          <StickyNote className="h-7 w-7" />
        </div>
      </div>

      <h2 className="m-0 text-h2 font-medium tracking-[-0.015em]">
        No notes yet for this project
      </h2>
      <p className="m-0 max-w-[720px] text-sm leading-[1.6] text-secondary">
        Notes capture decisions, reviews, and patterns that outlive any one
        deploy. They render as Markdown, carry tags you can filter, and can be
        pinned to stay at the top of this tab. Notes are also exposed to agents
        in the graph, providing project-level context across your workflows.
      </p>

      <Button className="mt-1 gap-1.5" onClick={() => onCreate()}>
        <Plus className="h-3 w-3" />
        New note
      </Button>

      <div className="mt-5 w-full max-w-[720px] text-overline uppercase text-tertiary">
        Or choose a template
      </div>
      <div className="grid w-full max-w-[720px] grid-cols-3 gap-2.5 text-left">
        {NOTE_TEMPLATES.map((t) => {
          const Icon = t.icon
          return (
            <button
              key={t.slug}
              type="button"
              onClick={() => onCreate(t.slug)}
              className="flex cursor-pointer flex-col gap-1.5 rounded-lg border border-tertiary bg-primary p-3.5 text-left hover:border-secondary hover:shadow-sm"
            >
              <div className="flex items-center gap-2">
                <div className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md bg-secondary text-secondary">
                  <Icon className="h-3.5 w-3.5" />
                </div>
                <span className="text-[13.5px] font-medium text-primary">
                  {t.label}
                </span>
                <span className="ml-auto">
                  <NoteTagChip tag={t.tag} size="sm" />
                </span>
              </div>
              <div className="text-xs leading-[1.5] text-tertiary">
                {t.hint}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

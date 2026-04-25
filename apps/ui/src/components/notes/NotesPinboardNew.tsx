import { ArrowLeft, Check, Columns2, Eye, PencilLine } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { NotesFilterRail } from './NotesFilterRail'
import { EMPTY_ACTIVE, tagCounts, uniqueTagsFromNotes } from './notesHelpers'
import { findTemplate } from './notesTemplates'
import { TagCombobox } from './TagCombobox'
import type { Note, TagRef } from '@/types'

type EditorMode = 'split' | 'write' | 'preview'

interface Props {
  orgSlug: string
  allNotes?: Note[]
  initialNote?: Note | null
  /**
   * When creating a new note, pre-seed the form from a template (currently
   * just its tag). Ignored when `initialNote` is provided.
   */
  templateSlug?: string
  onDiscard: () => void
  onSave: (draft: { title: string; content: string; tags: string[] }) => void
  saving?: boolean
}

const NOOP = () => {}

export function NotesPinboardNew({
  orgSlug,
  allNotes = [],
  initialNote,
  templateSlug,
  onDiscard,
  onSave,
  saving = false,
}: Props) {
  const railTags = useMemo(() => uniqueTagsFromNotes(allNotes), [allNotes])
  const railCounts = useMemo(() => tagCounts(allNotes), [allNotes])
  const isEditing = !!initialNote
  const template = !initialNote ? findTemplate(templateSlug) : null
  const [mode, setMode] = useState<EditorMode>('split')
  const [title, setTitle] = useState(initialNote?.title ?? '')
  const [content, setContent] = useState(initialNote?.content ?? '')
  const [tags, setTags] = useState<TagRef[]>(
    initialNote
      ? initialNote.tags.map((t) => ({ name: t.name, slug: t.slug }))
      : template
        ? [template.tag]
        : [],
  )

  const trimmedTitle = title.trim()
  const isValid = trimmedTitle.length > 0 && content.trim().length > 0
  const dirty = useMemo(() => {
    if (!initialNote)
      return trimmedTitle.length > 0 || content.length > 0 || tags.length > 0
    // Compare against the trimmed save value so trailing-space-only edits
    // don't masquerade as dirty.
    if (trimmedTitle !== initialNote.title.trim()) return true
    if (content !== initialNote.content) return true
    const initialSlugs = initialNote.tags
      .map((t) => t.slug)
      .sort()
      .join(',')
    const currentSlugs = tags
      .map((t) => t.slug)
      .sort()
      .join(',')
    return initialSlugs !== currentSlugs
  }, [initialNote, trimmedTitle, content, tags])
  const canSave = isValid && dirty

  const handleSave = () => {
    if (!canSave || saving) return
    onSave({
      title: title.trim(),
      content,
      tags: tags.map((t) => t.slug),
    })
  }

  const showEditor = mode !== 'preview'
  const showPreview = mode !== 'write'

  return (
    <div className="grid grid-cols-[220px_1fr] gap-5">
      {/* Rail stays visible but disabled while composing — preserves spatial continuity. */}
      <NotesFilterRail
        tags={railTags}
        counts={railCounts}
        active={EMPTY_ACTIVE}
        onToggle={NOOP}
        onClear={NOOP}
        search=""
        onSearchChange={NOOP}
        totalFiltered={allNotes.length}
        disabled
      />

      <div>
        {/* Toolbar */}
        <div className="mb-3.5 flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            onClick={onDiscard}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded border-0 bg-transparent px-1.5 py-1 text-xs text-secondary hover:bg-secondary hover:text-primary"
          >
            <ArrowLeft className="h-3 w-3" />
            All notes
          </button>
          <span className="text-tertiary">/</span>
          <span className="text-xs font-medium text-primary">
            {isEditing ? 'Edit note' : 'New note'}
          </span>

          <div className="ml-auto inline-flex gap-0.5 rounded-md border border-secondary bg-primary p-0.5">
            <ModeButton
              active={mode === 'split'}
              icon={<Columns2 className="h-3 w-3" />}
              onClick={() => setMode('split')}
            >
              Split
            </ModeButton>
            <ModeButton
              active={mode === 'write'}
              icon={<PencilLine className="h-3 w-3" />}
              onClick={() => setMode('write')}
            >
              Write
            </ModeButton>
            <ModeButton
              active={mode === 'preview'}
              icon={<Eye className="h-3 w-3" />}
              onClick={() => setMode('preview')}
            >
              Preview
            </ModeButton>
          </div>
          <div className="h-5 w-px bg-tertiary" />
          <Button variant="ghost" size="sm" onClick={onDiscard}>
            Discard
          </Button>
          <Button
            size="sm"
            className="gap-1.5"
            onClick={handleSave}
            disabled={!canSave || saving}
          >
            <Check className="h-3 w-3" />
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </div>

        <article className="overflow-hidden rounded-lg border border-tertiary bg-primary">
          {/* Title + tag picker */}
          <div className="px-7 pt-6">
            <div className="flex items-start gap-4">
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Title"
                autoFocus
                className="flex-1 border-0 bg-transparent p-0 text-[26px] font-medium leading-[1.2] tracking-[-0.015em] text-primary outline-none placeholder:text-tertiary"
              />
              <TagCombobox
                orgSlug={orgSlug}
                selected={tags}
                onChange={setTags}
              />
            </div>
          </div>

          {/* Editor panes */}
          <div
            className={cn(
              'mt-5 grid min-h-[560px] border-t border-tertiary',
              mode === 'split' ? 'grid-cols-2' : 'grid-cols-1',
            )}
          >
            {showEditor && (
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Start writing… Markdown supported."
                className={cn(
                  'min-h-[560px] w-full resize-none border-0 bg-primary px-7 py-5 font-mono text-[13px] leading-[1.65] text-primary outline-none placeholder:text-tertiary',
                  mode === 'split' && 'border-r border-tertiary',
                )}
                spellCheck
              />
            )}
            {showPreview && (
              <div className="flex flex-col">
                <div className="flex items-center gap-1.5 border-b border-tertiary bg-primary px-5 py-2 text-overline uppercase text-tertiary">
                  <Eye className="h-3 w-3" />
                  Preview
                </div>
                <div className="flex-1 bg-primary px-7 py-5">
                  <PreviewPane content={content} />
                </div>
              </div>
            )}
          </div>
        </article>
      </div>
    </div>
  )
}

function ModeButton({
  active,
  icon,
  onClick,
  children,
}: {
  active: boolean
  icon: ReactNode
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex h-6 cursor-pointer items-center gap-1.5 rounded-[5px] border-0 px-2.5 text-[12.5px] transition-colors',
        active
          ? 'bg-secondary text-primary'
          : 'bg-transparent text-secondary hover:text-primary',
      )}
    >
      {icon}
      {children}
    </button>
  )
}

function PreviewPane({ content }: { content: string }) {
  if (!content.trim()) {
    return (
      <div className="text-sm italic text-tertiary">
        Preview updates as you type.
      </div>
    )
  }
  return (
    <div className="note-markdown">
      <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
    </div>
  )
}

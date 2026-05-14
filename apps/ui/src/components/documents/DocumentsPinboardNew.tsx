import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { ArrowLeft, Check, Columns2, Eye, PencilLine } from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Document, DocumentTemplate, TagRef } from '@/types'

import { DocumentsFilterRail } from './DocumentsFilterRail'
import {
  EMPTY_ACTIVE,
  tagCounts,
  uniqueTagsFromDocuments,
} from './documentsHelpers'
import { TagCombobox } from './TagCombobox'

type EditorMode = 'preview' | 'split' | 'write'

interface Props {
  allDocuments?: Document[]
  initialDocument?: Document | null
  onDiscard: () => void
  onSave: (draft: { content: string; tags: string[]; title: string }) => void
  orgSlug: string
  saving?: boolean
  /**
   * When creating a new document, pre-seed the form (title, content, tags) from
   * the chosen template. Ignored when `initialDocument` is provided.
   */
  template?: DocumentTemplate | null
}

const NOOP = () => {}

export function DocumentsPinboardNew({
  allDocuments = [],
  initialDocument,
  onDiscard,
  onSave,
  orgSlug,
  saving = false,
  template,
}: Props) {
  const railTags = useMemo(
    () => uniqueTagsFromDocuments(allDocuments),
    [allDocuments],
  )
  const railCounts = useMemo(() => tagCounts(allDocuments), [allDocuments])
  const isEditing = !!initialDocument
  const seed = !initialDocument ? template : null
  const [mode, setMode] = useState<EditorMode>('split')
  const [title, setTitle] = useState(
    initialDocument?.title ?? seed?.title ?? '',
  )
  const [content, setContent] = useState(
    initialDocument?.content ?? seed?.content ?? '',
  )
  const [tags, setTags] = useState<TagRef[]>(
    initialDocument
      ? initialDocument.tags.map((t) => ({ name: t.name, slug: t.slug }))
      : seed?.tags
        ? seed.tags.map((t) => ({ name: t.name, slug: t.slug }))
        : [],
  )
  const titleRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const input = titleRef.current
    if (!input) return
    input.focus()
    const len = input.value.length
    input.setSelectionRange(len, len)
  }, [])

  const trimmedTitle = title.trim()
  const isValid = trimmedTitle.length > 0 && content.trim().length > 0
  const dirty = useMemo(() => {
    if (!initialDocument)
      return trimmedTitle.length > 0 || content.length > 0 || tags.length > 0
    // Compare against the trimmed save value so trailing-space-only edits
    // don't masquerade as dirty.
    if (trimmedTitle !== initialDocument.title.trim()) return true
    if (content !== initialDocument.content) return true
    const initialSlugs = initialDocument.tags
      .map((t) => t.slug)
      .sort()
      .join(',')
    const currentSlugs = tags
      .map((t) => t.slug)
      .sort()
      .join(',')
    return initialSlugs !== currentSlugs
  }, [initialDocument, trimmedTitle, content, tags])
  const canSave = isValid && dirty

  const handleSave = () => {
    if (!canSave || saving) return
    onSave({
      content,
      tags: tags.map((t) => t.slug),
      title: title.trim(),
    })
  }

  const showEditor = mode !== 'preview'
  const showPreview = mode !== 'write'

  return (
    <div className="grid grid-cols-[220px_1fr] gap-5">
      {/* Rail stays visible but disabled while composing — preserves spatial continuity. */}
      <DocumentsFilterRail
        active={EMPTY_ACTIVE}
        counts={railCounts}
        disabled
        onClear={NOOP}
        onSearchChange={NOOP}
        onToggle={NOOP}
        search=""
        tags={railTags}
        totalFiltered={allDocuments.length}
      />

      <div>
        {/* Toolbar */}
        <div className="mb-3.5 flex flex-wrap items-center gap-2.5">
          <Button onClick={onDiscard} size="sm" variant="ghost">
            <ArrowLeft className="size-3" />
            All documents
          </Button>
          <span className="text-tertiary">/</span>
          <span className="text-primary text-xs font-medium">
            {isEditing ? 'Edit document' : 'New document'}
          </span>

          <div className="border-secondary bg-primary ml-auto inline-flex gap-0.5 rounded-md border p-0.5">
            <ModeButton
              active={mode === 'split'}
              icon={<Columns2 className="size-3" />}
              onClick={() => setMode('split')}
            >
              Split
            </ModeButton>
            <ModeButton
              active={mode === 'write'}
              icon={<PencilLine className="size-3" />}
              onClick={() => setMode('write')}
            >
              Write
            </ModeButton>
            <ModeButton
              active={mode === 'preview'}
              icon={<Eye className="size-3" />}
              onClick={() => setMode('preview')}
            >
              Preview
            </ModeButton>
          </div>
          <div className="bg-tertiary h-5 w-px" />
          <Button onClick={onDiscard} size="sm" variant="ghost">
            Discard
          </Button>
          <Button
            className="gap-1.5"
            disabled={!canSave || saving}
            onClick={handleSave}
            size="sm"
          >
            <Check className="size-3" />
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </div>

        <article className="border-tertiary bg-primary overflow-hidden rounded-lg border">
          {/* Title + tag picker */}
          <div className="px-7 pt-6">
            <div className="flex items-start gap-4">
              <input
                className="text-primary placeholder:text-tertiary flex-1 border-0 bg-transparent p-0 text-[26px] leading-[1.2] font-medium tracking-[-0.015em] outline-none"
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Title"
                ref={titleRef}
                type="text"
                value={title}
              />
              <TagCombobox
                onChange={setTags}
                orgSlug={orgSlug}
                selected={tags}
              />
            </div>
          </div>

          {/* Editor panes */}
          <div
            className={cn(
              'mt-5 grid min-h-140 border-t border-tertiary',
              mode === 'split' ? 'grid-cols-2' : 'grid-cols-1',
            )}
          >
            {showEditor && (
              <textarea
                className={cn(
                  'min-h-140 w-full resize-none border-0 bg-primary px-7 py-5 font-mono text-[13px] leading-[1.65] text-primary outline-none placeholder:text-tertiary',
                  mode === 'split' && 'border-r border-tertiary',
                )}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Start writing… Markdown supported."
                spellCheck
                value={content}
              />
            )}
            {showPreview && (
              <div className="flex flex-col">
                <div className="border-tertiary bg-primary text-overline text-tertiary flex items-center gap-1.5 border-b px-5 py-2 uppercase">
                  <Eye className="size-3" />
                  Preview
                </div>
                <div className="bg-primary flex-1 px-7 py-5">
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
  children,
  icon,
  onClick,
}: {
  active: boolean
  children: ReactNode
  icon: ReactNode
  onClick: () => void
}) {
  return (
    <button
      className={cn(
        'inline-flex h-6 cursor-pointer items-center gap-1.5 rounded-[5px] border-0 px-2.5 text-[12.5px] transition-colors',
        active
          ? 'bg-secondary text-primary'
          : 'bg-transparent text-secondary hover:text-primary',
      )}
      onClick={onClick}
      type="button"
    >
      {icon}
      {children}
    </button>
  )
}

function PreviewPane({ content }: { content: string }) {
  if (!content.trim()) {
    return (
      <div className="text-tertiary text-sm italic">
        Preview updates as you type.
      </div>
    )
  }
  return (
    <div className="document-markdown">
      <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
    </div>
  )
}

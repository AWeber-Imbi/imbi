import type { CSSProperties, KeyboardEvent } from 'react'
import { useRef, useState } from 'react'

import {
  BoldItalicUnderlineToggles,
  CodeToggle,
  CreateLink,
  linkDialogPlugin,
  linkPlugin,
  listsPlugin,
  ListsToggle,
  markdownShortcutPlugin,
  MDXEditor,
  type MDXEditorMethods,
  quotePlugin,
  Separator,
  toolbarPlugin,
} from '@mdxeditor/editor'
import '@mdxeditor/editor/style.css'

import { ComposerActions, isSubmitChord } from './ComposerActions'
import { resolveMentions } from './mentions'

export interface RichCommentComposerProps {
  autoFocus?: boolean
  busy?: boolean
  /** Email → display_name, used to resolve typed @mentions on submit. */
  displayNames?: Map<string, string>
  /** Default content height in px; the user can drag to resize from there. */
  minHeight?: number
  onCancel?: () => void
  onSubmit: (body: string, mentions: string[]) => void
  placeholder?: string
  submitLabel?: string
}

/**
 * A WYSIWYG markdown composer built on `@mdxeditor/editor` (Lexical), with a
 * minimal toolbar. This is a spike: if it feels right we generalize it for
 * every markdown input (project descriptions, ops-log notes). It is
 * lazy-loaded so the Lexical bundle is only fetched when a composer opens.
 *
 * The editor emits markdown, so typed `@Display Name` text round-trips and is
 * resolved to emails on submit via `resolveMentions` — the same persistence
 * path as the plain composer. The `@`-autocomplete popover is not ported yet
 * (a Lexical mention plugin is a follow-up).
 */
export function RichCommentComposer({
  autoFocus = false,
  busy = false,
  displayNames,
  minHeight = 152,
  onCancel,
  onSubmit,
  placeholder = 'Add a comment…',
  submitLabel = 'Comment',
}: RichCommentComposerProps) {
  const ref = useRef<MDXEditorMethods>(null)
  const [text, setText] = useState('')
  const empty = !text.trim()

  const submit = () => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    onSubmit(trimmed, resolveMentions(trimmed, displayNames ?? new Map()))
    ref.current?.setMarkdown('')
    setText('')
  }

  // Lexical owns Enter; intercept Cmd/Ctrl-Enter (submit) and Escape (cancel)
  // on the capture phase before it reaches the editor.
  const onKeyDownCapture = (e: KeyboardEvent<HTMLDivElement>) => {
    if (isSubmitChord(e)) {
      e.preventDefault()
      submit()
    } else if (e.key === 'Escape') {
      onCancel?.()
    }
  }

  return (
    <div
      className="ds-mdx flex flex-col gap-1.5"
      onKeyDownCapture={onKeyDownCapture}
      style={{ '--ds-mdx-min-h': `${minHeight}px` } as CSSProperties}
    >
      <MDXEditor
        autoFocus={autoFocus}
        contentEditableClassName="ds-mdx-content"
        markdown=""
        onChange={setText}
        placeholder={placeholder}
        plugins={[
          listsPlugin(),
          quotePlugin(),
          linkPlugin(),
          linkDialogPlugin(),
          markdownShortcutPlugin(),
          toolbarPlugin({
            toolbarContents: () => (
              <>
                <BoldItalicUnderlineToggles options={['Bold', 'Italic']} />
                <Separator />
                <ListsToggle options={['bullet', 'number']} />
                <Separator />
                <CreateLink />
                <CodeToggle />
              </>
            ),
          }),
        ]}
        ref={ref}
      />
      <ComposerActions
        busy={busy}
        empty={empty}
        hint="Cmd + Enter to send"
        onCancel={onCancel}
        onSubmit={submit}
        submitLabel={submitLabel}
      />
    </div>
  )
}

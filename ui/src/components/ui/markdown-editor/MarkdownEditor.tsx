import { useRef, useState } from 'react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

import { MarkdownPreview } from './MarkdownPreview'
import { MarkdownToolbar } from './MarkdownToolbar'
import { useMarkdownFormatting } from './useMarkdownFormatting'

export interface MarkdownEditorProps {
  'aria-label'?: string
  /** Grow the textarea to fit its content; bound it with `max-h-*`. */
  autoResize?: boolean
  /** Classes for the outer frame. */
  className?: string
  disabled?: boolean
  /** Placed on the textarea, so a `<Label htmlFor>` targets it. */
  id?: string
  onChange: (value: string) => void
  placeholder?: string
  /** Classes for the textarea, e.g. `min-h-40 max-h-[60vh] font-mono`. */
  textareaClassName?: string
  value: string
}

type EditorTab = 'preview' | 'write'

/**
 * GitHub-style markdown field: Write / Preview tabs, a formatting toolbar
 * and Cmd/Ctrl-B/I/K shortcuts over a plain textarea. The value stays the
 * exact markdown the user typed — nothing is parsed and re-serialised.
 */
export function MarkdownEditor({
  'aria-label': ariaLabel,
  autoResize = false,
  className,
  disabled = false,
  id,
  onChange,
  placeholder,
  textareaClassName,
  value,
}: MarkdownEditorProps) {
  const [tab, setTab] = useState<EditorTab>('write')
  // The textarea's height when Preview opened, so the frame doesn't jump.
  const [previewMinHeight, setPreviewMinHeight] = useState<number>()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { format, onKeyDown } = useMarkdownFormatting(textareaRef, onChange)

  const changeTab = (next: string) => {
    if (next === 'preview') {
      setPreviewMinHeight(textareaRef.current?.offsetHeight || undefined)
    }
    setTab(next as EditorTab)
  }

  return (
    <Tabs
      className={cn(
        // Ring the frame only while typing; the tabs and toolbar buttons
        // show their own focus rings.
        'rounded-md border border-input bg-background has-[textarea:focus-visible]:ring-2 has-[textarea:focus-visible]:ring-ring has-[textarea:focus-visible]:ring-offset-2 has-[textarea:focus-visible]:ring-offset-background',
        className,
      )}
      onValueChange={changeTab}
      value={tab}
    >
      <div className="border-input flex flex-wrap items-center justify-between gap-x-4 border-b px-3">
        <TabsList className="h-9 w-auto gap-4 border-b-0">
          <TabsTrigger className="pb-1.5 text-xs" value="write">
            Write
          </TabsTrigger>
          <TabsTrigger className="pb-1.5 text-xs" value="preview">
            Preview
          </TabsTrigger>
        </TabsList>
        {tab === 'write' && (
          <MarkdownToolbar
            className="-mr-1.5 py-1"
            disabled={disabled}
            onFormat={format}
          />
        )}
      </div>
      {/* Kept mounted while previewing so the textarea's undo history
          survives a trip to the Preview tab. Radix doesn't hide
          force-mounted content itself. */}
      <TabsContent
        className="data-[state=inactive]:hidden"
        forceMount
        value="write"
      >
        <Textarea
          aria-label={ariaLabel}
          autoResize={autoResize}
          className={cn(
            'block rounded-t-none border-0 focus-visible:ring-0 focus-visible:ring-offset-0',
            textareaClassName,
          )}
          disabled={disabled}
          id={id}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          ref={textareaRef}
          value={value}
        />
      </TabsContent>
      <TabsContent
        className="px-3 py-2"
        style={{ minHeight: previewMinHeight }}
        value="preview"
      >
        <MarkdownPreview value={value} />
      </TabsContent>
    </Tabs>
  )
}

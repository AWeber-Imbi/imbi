import type { LucideIcon } from 'lucide-react'
import {
  Bold,
  Code,
  Heading,
  Italic,
  Link,
  List,
  ListOrdered,
  Quote,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Keystroke } from '@/components/ui/keystroke'
import { IconTooltip } from '@/components/ui/tooltip'
import type { MarkdownFormat } from '@/lib/markdown-format'
import { cn } from '@/lib/utils'

interface ToolbarAction {
  format: MarkdownFormat
  icon: LucideIcon
  label: string
  shortcut?: string
}

// Grouped like GitHub's comment toolbar: text, blocks, lists.
const GROUPS: ToolbarAction[][] = [
  [
    { format: 'heading', icon: Heading, label: 'Heading' },
    { format: 'bold', icon: Bold, label: 'Bold', shortcut: 'Ctrl+B' },
    { format: 'italic', icon: Italic, label: 'Italic', shortcut: 'Ctrl+I' },
  ],
  [
    { format: 'quote', icon: Quote, label: 'Quote' },
    { format: 'code', icon: Code, label: 'Code' },
    { format: 'link', icon: Link, label: 'Link', shortcut: 'Ctrl+K' },
  ],
  [
    { format: 'unorderedList', icon: List, label: 'Bulleted list' },
    { format: 'orderedList', icon: ListOrdered, label: 'Numbered list' },
  ],
]

interface MarkdownToolbarProps {
  className?: string
  disabled?: boolean
  onFormat: (format: MarkdownFormat) => void
}

/**
 * Formatting buttons for a markdown textarea. Pair with
 * `useMarkdownFormatting`, which supplies `onFormat` and the matching
 * keyboard shortcuts.
 */
export function MarkdownToolbar({
  className,
  disabled = false,
  onFormat,
}: MarkdownToolbarProps) {
  return (
    <div
      aria-label="Formatting"
      className={cn('flex items-center gap-2', className)}
      role="toolbar"
    >
      {GROUPS.map((group, i) => (
        <div className="flex items-center" key={i}>
          {group.map(({ format, icon: Icon, label, shortcut }) => (
            <IconTooltip
              key={format}
              label={
                <span className="flex items-center gap-2">
                  {label}
                  {shortcut && <Keystroke value={shortcut} />}
                </span>
              }
            >
              <Button
                aria-label={label}
                className="size-7 p-0 [&_svg]:size-4"
                disabled={disabled}
                onClick={() => onFormat(format)}
                // Keep focus (and the selection) in the textarea.
                onMouseDown={(e) => e.preventDefault()}
                size="sm"
                type="button"
                variant="ghost"
              >
                <Icon />
              </Button>
            </IconTooltip>
          ))}
        </div>
      ))}
    </div>
  )
}

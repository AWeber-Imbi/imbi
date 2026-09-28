import { RichMarkdown } from '@/components/ui/rich-markdown'
import { cn } from '@/lib/utils'

interface MarkdownPreviewProps {
  className?: string
  value: string
}

/** Rendered view of a markdown draft for the editor's Preview tab. */
export function MarkdownPreview({ className, value }: MarkdownPreviewProps) {
  if (!value.trim()) {
    return (
      <p className={cn('text-sm text-tertiary italic', className)}>
        Nothing to preview
      </p>
    )
  }
  return (
    <div
      className={cn(
        'document-markdown max-w-none text-sm [&>*:first-child]:mt-0 [&>*:last-child]:mb-0',
        className,
      )}
    >
      <RichMarkdown>{value}</RichMarkdown>
    </div>
  )
}

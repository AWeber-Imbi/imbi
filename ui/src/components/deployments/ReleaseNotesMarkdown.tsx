import { RichMarkdown } from '@/components/ui/rich-markdown'

interface ReleaseNotesMarkdownProps {
  notes: null | string | undefined
}

/** Markdown release-notes block shared by the deployment cards. */
export function ReleaseNotesMarkdown({ notes }: ReleaseNotesMarkdownProps) {
  if (!notes) {
    return <p className="text-tertiary text-xs italic">No release notes.</p>
  }
  return (
    <div className="document-markdown max-w-none text-sm [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <RichMarkdown>{notes}</RichMarkdown>
    </div>
  )
}

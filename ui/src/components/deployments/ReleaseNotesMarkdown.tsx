import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

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
      <Markdown
        components={{
          a: (props) => (
            <a {...props} rel="noopener noreferrer" target="_blank" />
          ),
        }}
        remarkPlugins={[remarkGfm]}
      >
        {notes}
      </Markdown>
    </div>
  )
}
